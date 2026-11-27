"""Model backends. Standard-library HTTP only (urllib), so nothing extra has to
install on a Windows review laptop.

* OllamaBackend          - local Ollama (default; Windows/macOS/Linux)
* OpenAICompatBackend    - LM Studio, llama.cpp server, vLLM, any /v1 endpoint
* ScriptedBackend        - deterministic fake used by the test-suite
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


class BackendError(RuntimeError):
    pass


@dataclass
class ChatResult:
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    raw: dict = field(default_factory=dict)


def _post(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise BackendError(f"HTTP {e.code} from {url}: {body}") from None
    except urllib.error.URLError as e:
        raise BackendError(f"cannot reach {url}: {e.reason}") from None
    except TimeoutError:
        raise BackendError(f"timeout after {timeout:.0f}s calling {url}") from None


def _get(url: str, timeout: float = 5.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise BackendError(f"cannot reach {url}: {e}") from None


class OllamaBackend:
    kind = "ollama"

    def __init__(self, host: str = "http://localhost:11434", timeout: float = 300.0):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._no_think: set[str] = set()

    def chat(self, model: str, messages: list[dict], schema: dict | None, options: dict) -> ChatResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",
            "options": {
                "temperature": options.get("temperature", 0.0),
                "seed": options.get("seed", 7),
                "num_ctx": options.get("num_ctx", 8192),
                "num_predict": options.get("max_tokens", 1024),
                "top_p": options.get("top_p", 0.9),
            },
        }
        if schema is not None:
            payload["format"] = schema
        if model not in self._no_think:
            payload["think"] = False
        for attempt in range(3):
            try:
                r = _post(f"{self.host}/api/chat", payload, self.timeout)
                break
            except BackendError as e:
                msg = str(e).lower()
                if "think" in msg and "think" in payload:
                    self._no_think.add(model)
                    payload.pop("think", None)
                    continue
                if attempt < 2 and ("timeout" in msg or "connection reset" in msg or "http 5" in msg):
                    if "timeout" in msg:
                        loaded = ", ".join(self.loaded_models()) or "none"
                        import sys
                        print(f"    ! {model} did not answer within {self.timeout:.0f}s (loaded: {loaded}); retrying. "
                              "If this repeats, the server may be unable to load another model: set "
                              "OLLAMA_MAX_LOADED_MODELS=4 and restart Ollama.", file=sys.stderr, flush=True)
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
        msg = r.get("message", {})
        return ChatResult(
            content=msg.get("content", "") or "",
            tokens_in=int(r.get("prompt_eval_count", 0) or 0),
            tokens_out=int(r.get("eval_count", 0) or 0),
            raw={"done_reason": r.get("done_reason")},
        )

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 32):
            r = _post(f"{self.host}/api/embed", {"model": model, "input": texts[i : i + 32],
                                                 "keep_alive": "30m"}, self.timeout)
            out.extend(r.get("embeddings", []))
        return out

    def list_models(self) -> list[str]:
        return [m.get("name", "") for m in _get(f"{self.host}/api/tags").get("models", [])]

    def loaded_models(self) -> list[str]:
        try:
            return [m.get("name", "") for m in _get(f"{self.host}/api/ps").get("models", [])]
        except BackendError:
            return []

    def version(self) -> str:
        return _get(f"{self.host}/api/version").get("version", "?")


class OpenAICompatBackend:
    kind = "openai"

    def __init__(self, base_url: str = "http://localhost:1234/v1", api_key: str = "local", timeout: float = 600.0):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.timeout = timeout

    def chat(self, model: str, messages: list[dict], schema: dict | None, options: dict) -> ChatResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": options.get("temperature", 0.0),
            "seed": options.get("seed", 7),
            "max_tokens": options.get("max_tokens", 1024),
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "out", "schema": schema, "strict": False}}
        try:
            r = _post(f"{self.base}/chat/completions", payload, self.timeout, self.headers)
        except BackendError as e:
            if schema is not None and "response_format" in str(e):
                payload["response_format"] = {"type": "json_object"}
                r = _post(f"{self.base}/chat/completions", payload, self.timeout, self.headers)
            else:
                raise
        choice = (r.get("choices") or [{}])[0]
        usage = r.get("usage") or {}
        return ChatResult(
            content=(choice.get("message") or {}).get("content", "") or "",
            tokens_in=int(usage.get("prompt_tokens", 0) or 0),
            tokens_out=int(usage.get("completion_tokens", 0) or 0),
        )

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 32):
            r = _post(f"{self.base}/embeddings", {"model": model, "input": texts[i : i + 32]},
                      self.timeout, self.headers)
            out.extend(d["embedding"] for d in sorted(r.get("data", []), key=lambda d: d.get("index", 0)))
        return out

    def list_models(self) -> list[str]:
        req = urllib.request.Request(f"{self.base}/models", headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return [m["id"] for m in json.loads(resp.read().decode("utf-8")).get("data", [])]
        except Exception as e:  # noqa: BLE001
            raise BackendError(f"cannot reach {self.base}: {e}") from None

    def version(self) -> str:
        return "openai-compatible"


Handler = Callable[[str, list[dict], "dict | None"], Any]


class ScriptedBackend:
    """Test double. `handler(prompt_id, messages, schema)` returns a dict/list
    (serialised to JSON) or a string. Embeddings are deterministic hashed
    bag-of-words vectors so retrieval behaves sensibly in tests."""

    kind = "scripted"

    def __init__(self, handler: Handler, dim: int = 256):
        self.handler = handler
        self.dim = dim
        self.calls: list[dict] = []

    def chat(self, model: str, messages: list[dict], schema: dict | None, options: dict) -> ChatResult:
        pid = options.get("prompt_id", "?")
        self.calls.append({"prompt_id": pid, "model": model, "messages": messages})
        out = self.handler(pid, messages, schema)
        content = out if isinstance(out, str) else json.dumps(out)
        return ChatResult(content=content, tokens_in=sum(len(m["content"]) // 4 for m in messages),
                          tokens_out=len(content) // 4)

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        import hashlib
        import re

        vecs = []
        for t in texts:
            v = [0.0] * self.dim
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0
            vecs.append(v)
        return vecs

    def list_models(self) -> list[str]:
        return ["scripted"]

    def version(self) -> str:
        return "scripted"
