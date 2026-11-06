"""Small, dependency-free statistics for attack success rates."""

import math

Z95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (well-behaved at 0%, 100%, small n)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def fmt_rate(successes: int, n: int) -> str:
    """'12.5% [6.1–23.9]' — rate with 95% Wilson CI, or 'n/a'."""
    if n == 0:
        return "n/a"
    lo, hi = wilson(successes, n)
    return f"{successes / n:.1%} [{lo:.1%}–{hi:.1%}]"


def two_proportion_p(s1: int, n1: int, s2: int, n2: int) -> float:
    """Two-sided p-value of a pooled two-proportion z-test (difference in success rates)."""
    if n1 == 0 or n2 == 0:
        return float("nan")
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (s1 / n1 - s2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def quantiles(values: list[float], qs=(0.5, 0.9, 0.99)) -> list[float]:
    """Nearest-rank-with-interpolation quantiles; empty list -> NaNs."""
    if not values:
        return [float("nan")] * len(qs)
    xs = sorted(values)
    out = []
    for q in qs:
        pos = q * (len(xs) - 1)
        lo, hi = math.floor(pos), math.ceil(pos)
        out.append(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))
    return out
