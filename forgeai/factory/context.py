"""Shared state for one factory run and helpers to build the model gateway."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from forgeai.config import Settings
from forgeai.ingest.chunker import Chunk
from forgeai.ingest.loaders import Document
from forgeai.llm.backends import OllamaBackend, OpenAICompatBackend
from forgeai.llm.cache import LayeredCache, SqliteStore
from forgeai.llm.gateway import Budget, Gateway, RoleConfig
from forgeai.retrieval.index import KnowledgeIndex
from forgeai.util import console as C


def make_backend(settings: Settings):
    if settings.backend == "openai":
        return OpenAICompatBackend(settings.host, settings.api_key)
    return OllamaBackend(settings.host)


def make_gateway(settings: Settings, run_dir: Path | None = None, backend=None,
                 replay: bool | None = None) -> Gateway:
    backend = backend or make_backend(settings)
    replay = settings.replay if replay is None else replay
    stores = []
    if run_dir is not None:
        stores.append(SqliteStore(Path(run_dir) / "llm_cache.sqlite", readonly=False))
    if not replay and settings.cache_dir:
        stores.append(SqliteStore(Path(settings.cache_dir) / "llm_cache.sqlite"))
    roles = {
        "factory": RoleConfig(settings.factory_model, backend, 0.0, settings.num_ctx, 1400),
        "agent": RoleConfig(settings.agent_model, backend, 0.0, settings.num_ctx, 700),
        "judge": RoleConfig(settings.judge_model, backend, 0.0, settings.num_ctx, 600),
    }
    return Gateway(roles, embed_backend=backend, embed_model=settings.embed_model,
                   cache=LayeredCache(stores) if stores else None, replay=replay,
                   trace_path=(Path(run_dir) / "trace.jsonl") if run_dir else None,
                   budget=Budget(settings.max_minutes * 60, settings.max_tokens), seed=settings.seed)


@dataclass
class Run:
    settings: Settings
    run_dir: Path
    gw: Gateway
    brief: str = ""
    docs_dir: Path | None = None
    docs: list[Document] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    index: KnowledgeIndex | None = None
    profiles: dict = field(default_factory=dict)
    requirements: dict = field(default_factory=dict)
    groundability: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def path(self, *parts: str) -> Path:
        p = self.run_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def pmap(self, fn: Callable[[Any], Any], items: Iterable[Any], label: str = "") -> list:
        items = list(items)
        if not items:
            return []
        prog = C.Progress(len(items), label) if label else None
        workers = max(1, min(self.settings.workers, len(items)))

        def wrapped(x):
            try:
                return fn(x)
            finally:
                if prog:
                    prog.tick()

        if workers == 1:
            out = [wrapped(x) for x in items]
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                out = list(ex.map(wrapped, items))
        if prog:
            prog.close()
        return out

    def corpus_card(self, max_chars: int = 3500) -> str:
        lines = []
        for d in self.docs:
            prof = self.profiles.get(d.doc_id, {})
            extra = f" | table columns: {', '.join(d.table.columns[:14])}; {len(d.table.rows)} rows" if d.table else ""
            lines.append(f"- {d.path} ({d.kind}){extra}\n  {prof.get('summary', d.title)}\n  topics: "
                         f"{', '.join(prof.get('topics', [])[:8])}")
        txt = "\n".join(lines)
        return txt if len(txt) <= max_chars else txt[:max_chars] + "\n- ..."
