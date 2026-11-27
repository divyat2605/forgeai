"""The single door every model call goes through.

Responsibilities: role -> (backend, model) routing, schema-constrained decoding
plus validation and bounded repair, content-addressed caching (replayable
runs), token/latency metering per stage, budget enforcement, and a JSONL trace
of every call. Factory code never talks to a backend directly.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forgeai.llm import prompts as prompt_store
from forgeai.llm.backends import BackendError
from forgeai.llm.cache import LayeredCache
from forgeai.llm.schema import coerce, extract_json, validate
from forgeai.util.io import append_jsonl, hash_obj, sha256_text


class LLMError(RuntimeError):
    pass


class LLMOutputError(LLMError):
    """The model could not produce schema-valid output within the retry budget."""


class BudgetExceeded(LLMError):
    pass


class ReplayMiss(LLMError):
    pass


@dataclass
class RoleConfig:
    model: str
    backend: Any
    temperature: float = 0.0
    num_ctx: int = 8192
    max_tokens: int = 1024


@dataclass
class Budget:
    max_seconds: float = 0.0       # 0 = unlimited
    max_tokens: int = 0            # fresh (uncached) tokens; 0 = unlimited


@dataclass
class Meter:
    t0: float = field(default_factory=time.time)
    calls: int = 0
    cache_hits: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model_seconds: float = 0.0
    repairs: int = 0
    failures: int = 0
    by_stage: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, stage: str, tin: int, tout: int, secs: float, hit: bool) -> None:
        with self.lock:
            self.calls += 1
            s = self.by_stage.setdefault(stage, {"calls": 0, "cache_hits": 0, "tokens_in": 0,
                                                 "tokens_out": 0, "model_seconds": 0.0})
            s["calls"] += 1
            if hit:
                self.cache_hits += 1
                s["cache_hits"] += 1
                return
            self.tokens_in += tin
            self.tokens_out += tout
            self.model_seconds += secs
            s["tokens_in"] += tin
            s["tokens_out"] += tout
            s["model_seconds"] = round(s["model_seconds"] + secs, 3)

    @property
    def fresh_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def elapsed(self) -> float:
        return time.time() - self.t0

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "wall_seconds": round(self.elapsed(), 1),
                "calls": self.calls,
                "cache_hits": self.cache_hits,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "model_seconds": round(self.model_seconds, 1),
                "repairs": self.repairs,
                "failures": self.failures,
                "by_stage": json.loads(json.dumps(self.by_stage)),
            }


class Gateway:
    def __init__(self, roles: dict[str, RoleConfig], embed_backend: Any = None, embed_model: str = "",
                 cache: LayeredCache | None = None, replay: bool = False, trace_path: Path | None = None,
                 budget: Budget | None = None, seed: int = 7, max_repairs: int = 2):
        self.roles = roles
        self.embed_backend = embed_backend
        self.embed_model = embed_model
        self.cache = cache
        self.replay = replay
        self.trace_path = trace_path
        self.budget = budget or Budget()
        self.meter = Meter()
        self.seed = seed
        self.max_repairs = max_repairs
        self._trace_lock = threading.Lock()

    # ------------------------------------------------------------------ budget
    def budget_left(self) -> float:
        """Fraction of the tightest budget still available (1.0 if unlimited)."""
        fr = [1.0]
        if self.budget.max_seconds:
            fr.append(1 - self.meter.elapsed() / self.budget.max_seconds)
        if self.budget.max_tokens:
            fr.append(1 - self.meter.fresh_tokens / self.budget.max_tokens)
        return max(0.0, min(fr))

    def overspend(self) -> float:
        """How far past the tightest budget we are (0 = within budget)."""
        fr = [0.0]
        if self.budget.max_seconds:
            fr.append(self.meter.elapsed() / self.budget.max_seconds - 1)
        if self.budget.max_tokens:
            fr.append(self.meter.fresh_tokens / self.budget.max_tokens - 1)
        return max(fr)

    def _check_budget(self) -> None:
        # Soft budget: stages adapt (smaller eval set, no tournament, early-stopped loop) and the
        # optimizer stops itself. Only a run 25% past its budget is cut off as a safety ceiling.
        if self.overspend() > 0.25:
            raise BudgetExceeded("run budget exhausted (25% overspend ceiling)")

    # ------------------------------------------------------------------- trace
    def _trace(self, rec: dict) -> None:
        if self.trace_path is None:
            return
        with self._trace_lock:
            append_jsonl(self.trace_path, rec)

    # -------------------------------------------------------------------- chat
    def model_of(self, role: str) -> str:
        return self.roles[role].model

    def _raw_chat(self, role: str, messages: list[dict], schema: dict | None, stage: str,
                  prompt_id: str, temperature: float | None, max_tokens: int | None):
        rc = self.roles[role]
        opts = {"temperature": rc.temperature if temperature is None else temperature,
                "seed": self.seed, "num_ctx": rc.num_ctx,
                "max_tokens": max_tokens or rc.max_tokens}
        key = hash_obj({"b": getattr(rc.backend, "kind", "?"), "m": rc.model, "msgs": messages,
                        "schema": schema, "opts": opts})
        if self.cache is not None:
            row = self.cache.get_chat(key)
            if row is not None:
                self.meter.add(stage, row[1], row[2], 0.0, True)
                self._trace({"t": round(time.time(), 3), "stage": stage, "role": role, "model": rc.model,
                             "prompt": prompt_id, "cache": True, "key": key[:16]})
                return row[0]
        if self.replay:
            raise ReplayMiss(f"replay: no cached response for {prompt_id} ({stage})")
        self._check_budget()
        t = time.time()
        try:
            res = rc.backend.chat(rc.model, messages, schema, {**opts, "prompt_id": prompt_id})
        except BackendError as e:
            with self.meter.lock:
                self.meter.failures += 1
            raise LLMError(str(e)) from None
        secs = time.time() - t
        self.meter.add(stage, res.tokens_in, res.tokens_out, secs, False)
        self._trace({"t": round(time.time(), 3), "stage": stage, "role": role, "model": rc.model,
                     "prompt": prompt_id, "cache": False, "key": key[:16], "tin": res.tokens_in,
                     "tout": res.tokens_out, "secs": round(secs, 2)})
        if self.cache is not None and res.content:
            self.cache.put_chat(key, res.content, res.tokens_in, res.tokens_out)
        return res.content

    def chat_text(self, role: str, messages: list[dict], stage: str, prompt_id: str = "adhoc",
                  temperature: float | None = None, max_tokens: int | None = None) -> str:
        return self._raw_chat(role, messages, None, stage, prompt_id, temperature, max_tokens)

    def chat_json(self, role: str, messages: list[dict], schema: dict, stage: str,
                  prompt_id: str = "adhoc", temperature: float | None = None,
                  max_tokens: int | None = None) -> Any:
        msgs = list(messages)
        last_err = ""
        for attempt in range(self.max_repairs + 1):
            content = self._raw_chat(role, msgs, schema, stage, prompt_id,
                                     temperature if attempt == 0 else (temperature or 0.0) + 0.2 * attempt,
                                     max_tokens)
            try:
                value = coerce(extract_json(content), schema)
                errs = validate(value, schema)
            except ValueError as e:
                value, errs = None, [str(e)]
            if not errs:
                return value
            last_err = "; ".join(errs[:6])
            with self.meter.lock:
                self.meter.repairs += 1
            msgs = msgs + [
                {"role": "assistant", "content": content[:4000]},
                {"role": "user", "content": "Your reply did not match the required JSON schema: "
                 f"{last_err}. Reply again with ONLY corrected JSON that satisfies the schema."},
            ]
        with self.meter.lock:
            self.meter.failures += 1
        raise LLMOutputError(f"{prompt_id}: schema-invalid after {self.max_repairs} repairs ({last_err})")

    def run_prompt(self, role: str, prompt_id: str, schema: dict | None, stage: str,
                   temperature: float | None = None, max_tokens: int | None = None, **variables) -> Any:
        system, user, _ = prompt_store.render(prompt_id, **variables)
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        if schema is None:
            return self.chat_text(role, msgs, stage, prompt_id, temperature, max_tokens)
        return self.chat_json(role, msgs, schema, stage, prompt_id, temperature, max_tokens)

    # --------------------------------------------------------------- embedding
    def embed(self, texts: list[str], stage: str = "embed") -> list[list[float]]:
        if self.embed_backend is None or not self.embed_model:
            raise LLMError("no embedding model configured")
        keys = [sha256_text(self.embed_model + "\x00" + t) for t in texts]
        out: list[list[float] | None] = [None] * len(texts)
        missing = []
        for i, k in enumerate(keys):
            v = self.cache.get_emb(k) if self.cache is not None else None
            if v is None:
                missing.append(i)
            else:
                out[i] = v
        if missing:
            if self.replay:
                raise ReplayMiss("replay: embeddings missing from cache")
            t = time.time()
            try:
                vecs = self.embed_backend.embed(self.embed_model, [texts[i] for i in missing])
            except BackendError as e:
                raise LLMError(str(e)) from None
            self.meter.add(stage, sum(len(texts[i]) // 4 for i in missing), 0, time.time() - t, False)
            for i, v in zip(missing, vecs):
                out[i] = v
            if self.cache is not None:
                self.cache.put_emb_many([(keys[i], out[i]) for i in missing])
        return out  # type: ignore[return-value]
