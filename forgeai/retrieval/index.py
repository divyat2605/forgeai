"""Hybrid retrieval: BM25 + dense embeddings, fused by weighted reciprocal rank.

Lexical search catches exact part numbers, clause ids and policy names that
small embedding models blur; dense search catches paraphrase. Fusion weight,
top_k and neighbour expansion are agent-definition parameters the optimizer
tunes against measured retrieval recall, not guesses.

The index persists next to the agent definition (chunks.json + vectors.npy)
so the chat runner loads instantly and offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from forgeai.ingest.chunker import Chunk
from forgeai.retrieval.bm25 import BM25
from forgeai.util.io import atomic_write_text

QUERY_PREFIX = {"nomic": ("search_query: ", "search_document: "),
                "mxbai": ("Represent this sentence for searching relevant passages: ", ""),
                "bge": ("Represent this sentence for searching relevant passages: ", ""),
                "embeddinggemma": ("task: search result | query: ", "title: none | text: ")}


def prefixes(model: str) -> tuple[str, str]:
    m = (model or "").lower()
    for key, val in QUERY_PREFIX.items():
        if key in m:
            return val
    return ("", "")


@dataclass
class Hit:
    chunk: Chunk
    score: float          # fused score (rank-based)
    dense: float          # cosine similarity (0 if no dense index)
    lexical: float        # raw BM25
    neighbour: bool = False


class KnowledgeIndex:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray | None, embed_model: str = ""):
        self.chunks = chunks
        self.by_id = {c.chunk_id: c for c in chunks}
        self.embed_model = embed_model
        self.vectors = vectors
        if vectors is not None and len(vectors):
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            self.unit = vectors / np.maximum(norms, 1e-9)
        else:
            self.unit = None
        self.bm25 = BM25([c.indexed_text for c in chunks])
        self._order = {c.chunk_id: i for i, c in enumerate(chunks)}

    # ----------------------------------------------------------------- build
    @classmethod
    def build(cls, chunks: list[Chunk], gateway=None, stage: str = "index") -> "KnowledgeIndex":
        vectors = None
        model = ""
        if gateway is not None and gateway.embed_model:
            model = gateway.embed_model
            _, dpre = prefixes(model)
            vecs = gateway.embed([dpre + c.indexed_text[:2000] for c in chunks], stage=stage)
            vectors = np.asarray(vecs, dtype=np.float32) if vecs else None
        return cls(chunks, vectors, model)

    def save(self, folder: Path) -> None:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(folder / "chunks.json",
                          json.dumps({"embed_model": self.embed_model,
                                      "chunks": [c.to_dict() for c in self.chunks]}, ensure_ascii=False))
        if self.vectors is not None:
            np.save(folder / "vectors.npy", self.vectors.astype(np.float32))

    @classmethod
    def load(cls, folder: Path) -> "KnowledgeIndex":
        folder = Path(folder)
        data = json.loads((folder / "chunks.json").read_text(encoding="utf-8"))
        vp = folder / "vectors.npy"
        vectors = np.load(vp) if vp.exists() else None
        return cls([Chunk.from_dict(c) for c in data["chunks"]], vectors, data.get("embed_model", ""))

    # ---------------------------------------------------------------- search
    def query_vector(self, query: str, gateway) -> np.ndarray | None:
        if self.unit is None or gateway is None or not self.embed_model:
            return None
        qpre, _ = prefixes(self.embed_model)
        v = np.asarray(gateway.embed([qpre + query], stage="retrieve")[0], dtype=np.float32)
        return v / max(float(np.linalg.norm(v)), 1e-9)

    def search(self, query: str, top_k: int = 6, bm25_weight: float = 0.4, gateway=None,
               neighbours: int = 0, qvec: np.ndarray | None = None, rrf_k: int = 60) -> list[Hit]:
        if not self.chunks:
            return []
        lex = self.bm25.scores(query)
        if qvec is None:
            qvec = self.query_vector(query, gateway)
        dense = (self.unit @ qvec).tolist() if (qvec is not None and self.unit is not None) else [0.0] * len(self.chunks)
        n = len(self.chunks)
        lex_rank = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: -lex[i]))}
        has_dense = qvec is not None and self.unit is not None
        dense_rank = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: -dense[i]))} if has_dense else {}
        w_lex = bm25_weight if has_dense else 1.0
        w_den = (1 - bm25_weight) if has_dense else 0.0
        fused = []
        for i in range(n):
            s = w_lex / (rrf_k + lex_rank[i]) if lex[i] > 0 else 0.0
            if has_dense:
                s += w_den / (rrf_k + dense_rank[i])
            fused.append(s)
        order = sorted(range(n), key=lambda i: -fused[i])[:top_k]
        hits = [Hit(self.chunks[i], fused[i], float(dense[i]), float(lex[i])) for i in order if fused[i] > 0]
        if neighbours > 0:
            have = {h.chunk.chunk_id for h in hits}
            extra: list[Hit] = []
            for h in hits[: max(1, top_k // 2)]:
                idx = self._order[h.chunk.chunk_id]
                for j in range(idx - neighbours, idx + neighbours + 1):
                    if 0 <= j < n and j != idx:
                        c = self.chunks[j]
                        if c.doc_id == h.chunk.doc_id and c.kind == "text" and c.chunk_id not in have:
                            have.add(c.chunk_id)
                            extra.append(Hit(c, 0.0, float(dense[j]), float(lex[j]), neighbour=True))
            hits.extend(extra)
        return hits

    def doc_ids(self) -> list[str]:
        return sorted({c.doc_id for c in self.chunks})
