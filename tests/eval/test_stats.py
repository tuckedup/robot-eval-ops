from __future__ import annotations

import math

import pytest

from robotevalops.metrics.stats import describe, exact_mcnemar_p, wilson_interval


def _ref(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Independent closed form: solve (p - x)^2 = z^2 x(1-x)/n as a quadratic in x."""
    p = k / n
    a = 1 + z * z / n
    b = -(2 * p + z * z / n)
    c = p * p
    disc = math.sqrt(b * b - 4 * a * c)
    return (-b - disc) / (2 * a), (-b + disc) / (2 * a)


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [(0, 10, 0.0, 0.2775), (10, 10, 0.7225, 1.0), (5, 10, 0.2366, 0.7634), (8, 10, 0.4902, 0.9433)],
)
def test_wilson_known_values(k, n, lo, hi):
    got = wilson_interval(k, n)
    assert got is not None
    assert got[0] == pytest.approx(lo, abs=1e-4)
    assert got[1] == pytest.approx(hi, abs=1e-4)


@pytest.mark.parametrize("k,n", [(0, 1), (1, 1), (3, 7), (14, 20), (1, 100)])
def test_wilson_matches_quadratic_reference(k, n):
    lo, hi = wilson_interval(k, n)
    rlo, rhi = _ref(k, n)
    assert lo == pytest.approx(max(0.0, rlo), abs=1e-9)
    assert hi == pytest.approx(min(1.0, rhi), abs=1e-9)


def test_wilson_n_zero_is_none_and_bad_counts_raise():
    assert wilson_interval(0, 0) is None
    with pytest.raises(ValueError):
        wilson_interval(3, 2)


def test_describe_empty_and_p95_gate():
    assert describe([])["mean"] is None and describe([])["n"] == 0
    d = describe([1.0, 2.0, 3.0])
    assert d == {"n": 3, "mean": 2.0, "median": 2.0, "min": 1.0, "max": 3.0, "p95": None}
    d20 = describe([float(i) for i in range(1, 21)])
    assert d20["p95"] == 19.0  # nearest rank: ceil(0.95*20)=19th value


def test_exact_mcnemar_hand_computed():
    # b=1, c=5: n=6, P(X<=1)=(1+6)/64 -> p = 14/64
    assert exact_mcnemar_p(1, 5) == pytest.approx(0.21875)
    assert exact_mcnemar_p(0, 10) == pytest.approx(2 / 1024)
    assert exact_mcnemar_p(3, 3) == 1.0
    assert exact_mcnemar_p(0, 0) is None
