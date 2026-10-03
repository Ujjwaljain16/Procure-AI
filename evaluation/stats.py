"""Statistics for the evaluation claims.

Exact paired sign test for an architecture comparison on the same cases, and a
percentile bootstrap confidence interval for a median. Both use only the
standard library, so the numbers in the docs can be reproduced exactly.
"""

from __future__ import annotations

import random
import statistics
from math import comb
from typing import Sequence


def exact_sign_test(a: Sequence[float], b: Sequence[float]) -> dict:
    """Two-sided exact sign test on paired observations (ties are dropped)."""
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [x - y for x, y in zip(a, b) if x != y]
    n = len(diffs)
    if n == 0:
        return {"n_nonzero": 0, "a_greater": 0, "p_two_sided": 1.0}
    a_greater = sum(1 for d in diffs if d > 0)
    k = min(a_greater, n - a_greater)
    tail = sum(comb(n, i) for i in range(0, k + 1)) / 2**n
    return {"n_nonzero": n, "a_greater": a_greater, "p_two_sided": min(1.0, 2 * tail)}


def bootstrap_median_ci(values: Sequence[float], confidence: float = 0.95, resamples: int = 10000, seed: int = 0) -> dict:
    """Percentile bootstrap CI for the median. Seeded, so reruns match."""
    if not values:
        raise ValueError("no values")
    rng = random.Random(seed)
    n = len(values)
    medians = sorted(statistics.median(rng.choices(values, k=n)) for _ in range(resamples))
    lo_idx = int(((1 - confidence) / 2) * resamples)
    hi_idx = min(resamples - 1, int((1 - (1 - confidence) / 2) * resamples))
    return {"median": statistics.median(values), "low": medians[lo_idx], "high": medians[hi_idx], "n": n, "seed": seed}
