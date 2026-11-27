"""Run settings and model profiles.

Profiles pick small open models that run on an ordinary laptop through Ollama.
The judge is deliberately from a DIFFERENT model family than the agent, so the
judge is not grading its own family's writing (self-preference bias).
Everything can be overridden by CLI flags or FORGE_* environment variables.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROFILES: dict[str, dict[str, str]] = {
    # Measured on the HR demo eval set (docs/MODEL_SELECTION.md). Every profile keeps exactly
    # three models resident, which fits Ollama's default OLLAMA_MAX_LOADED_MODELS=3 (no setup needed).
    # best measured agent (0 hallucinations); needs a GPU / Apple silicon for comfortable speed
    "standard": {"factory_model": "qwen3:8b", "agent_model": "qwen3:8b", "judge_model": "gemma3:4b",
                 "embed_model": "nomic-embed-text"},
    # 8-16 GB RAM, CPU-only laptops
    "laptop": {"factory_model": "qwen3:4b", "agent_model": "qwen3:4b", "judge_model": "gemma3:4b",
               "embed_model": "nomic-embed-text"},
    # very slow machines
    "tiny": {"factory_model": "qwen3:1.7b", "agent_model": "qwen3:1.7b", "judge_model": "gemma3:4b",
             "embed_model": "nomic-embed-text"},
}


@dataclass
class Settings:
    profile: str = "standard"
    backend: str = "ollama"                 # ollama | openai
    host: str = "http://localhost:11434"    # ollama host or OpenAI-compatible base URL
    api_key: str = "local"
    factory_model: str = ""
    agent_model: str = ""
    judge_model: str = ""
    embed_model: str = ""
    workers: int = 4
    max_iterations: int = 3
    eval_target: int = 32                   # generated cases kept (>= 20 required)
    holdout_frac: float = 0.4
    seed: int = 7
    max_minutes: float = 0.0                # 0 = unlimited
    max_tokens: int = 0                     # fresh tokens, 0 = unlimited
    min_gain: float = 0.03                  # stop when an iteration gains less than this (dev pass rate)
    max_questions: int = 5
    interactive: bool = True
    approve_requirements: bool = False      # human checkpoint
    tournament: bool = True
    offline_tools: bool = False
    num_ctx: int = 8192
    cache_dir: Path = field(default_factory=lambda: Path(os.environ.get("FORGE_CACHE", ".forge_cache")))
    replay: bool = False

    def resolve(self) -> "Settings":
        prof = PROFILES.get(self.profile, PROFILES["standard"])
        for k, v in prof.items():
            env = os.environ.get(f"FORGE_{k.upper()}")
            if not getattr(self, k):
                setattr(self, k, env or v)
        if self.backend == "openai" and self.host == "http://localhost:11434":
            self.host = os.environ.get("FORGE_OPENAI_BASE", "http://localhost:1234/v1")
        return self

    def public(self) -> dict:
        d = asdict(self)
        d["cache_dir"] = Path(d["cache_dir"]).as_posix()
        d.pop("api_key", None)
        return d


def family(model: str) -> str:
    m = model.lower().split(":")[0]
    for fam in ("qwen", "gemma", "llama", "mistral", "phi", "granite", "deepseek", "olmo", "smollm"):
        if fam in m:
            return fam
    return m
