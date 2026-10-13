"""Small statistics helpers (stdlib only). Every function is explicit about n=0 and never invents numbers."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

Z95 = 1.96
P95_MIN_N = 20


def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion k/n.

    center = (p + z^2/2n) / (1 + z^2/n); half = z*sqrt(p(1-p)/n + z^2/4n^2) / (1 + z^2/n).
    Returns None when n == 0 (no data: an interval of [0, 1] would look like information).
    """
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"invalid counts k={k}, n={n}: need 0 <= k <= n")
    if n == 0:
        return None
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def rate(k: int, n: int) -> float | None:
    """k/n, or None when the denominator is zero."""
    return None if n == 0 else k / n


def percentile_nearest_rank(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in (0, 100]). Requires at least one value."""
    if not values:
        raise ValueError("percentile of empty sequence")
    s = sorted(values)
    idx = max(1, math.ceil(q / 100.0 * len(s))) - 1
    return s[idx]


def describe(values: Sequence[float]) -> dict[str, float | int | None]:
    """mean/median/min/max/n from recorded values only; None everywhere when n == 0.
    p95 is reported only when n >= P95_MIN_N (otherwise None)."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None, "p95": None}
    return {
        "n": n,
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "p95": percentile_nearest_rank(values, 95) if n >= P95_MIN_N else None,
    }


def exact_mcnemar_p(b: int, c: int) -> float | None:
    """Exact two-sided McNemar test (binomial sign test) on discordant counts b, c.

    Under H0 each discordant pair is equally likely to favour either side: X ~ Binomial(b+c, 1/2).
    p = min(1, 2 * P(X <= min(b, c))). Returns None when b + c == 0 (the test is undefined).
    """
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    n = b + c
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2.0 * tail / 2**n)
