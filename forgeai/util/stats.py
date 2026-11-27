"""Small-sample statistics. With 20-40 eval cases a point estimate alone is
misleading, so every headline number carries an interval, and every accepted
change carries a paired test."""

from __future__ import annotations

import math
import random
from typing import Sequence


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value. b = pass->fail flips, c = fail->pass flips."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def paired_flips(before: dict[str, bool], after: dict[str, bool]) -> dict:
    ids = sorted(set(before) & set(after))
    fixed = [i for i in ids if not before[i] and after[i]]
    broke = [i for i in ids if before[i] and not after[i]]
    return {
        "n": len(ids),
        "fixed": fixed,
        "broke": broke,
        "net": len(fixed) - len(broke),
        "p_value": mcnemar_exact(len(broke), len(fixed)),
    }


def bootstrap_mean_ci(values: Sequence[float], iters: int = 2000, seed: int = 7) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    return (means[int(0.025 * iters)], means[int(0.975 * iters) - 1])


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"
