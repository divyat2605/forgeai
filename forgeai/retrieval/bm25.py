"""Okapi BM25 over stemmed content tokens (pure Python, deterministic)."""

from __future__ import annotations

import math
from collections import Counter

from forgeai.util.text import tokens


class BM25:
    def __init__(self, texts: list[str], k1: float = 1.4, b: float = 0.72):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokens(t, content_only=True)) for t in texts]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 1.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokens(query, content_only=True)
        out = []
        for d, ln in zip(self.docs, self.lens):
            s = 0.0
            for t in q:
                tf = d.get(t, 0)
                if tf:
                    s += self.idf.get(t, 0.0) * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * ln / self.avg))
            out.append(s)
        return out
