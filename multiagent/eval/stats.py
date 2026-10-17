"""Pure statistics for the eval report (U28, AM-22). No I/O."""

from collections import Counter
from collections.abc import Sequence
from math import sqrt

Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. n == 0 gives the vacuous (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    if not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k} n={n}")
    p, z2 = k / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def class_counts(labels: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(labels).items()))


def false_same(expected: Sequence[str], got: Sequence[str]) -> tuple[int, int]:
    """(k, n): k changed cases called `same`, out of n changed cases.
    A case is changed when its expected label is not `same`. This is the key safety number."""
    if len(expected) != len(got):
        raise ValueError("expected and got must be the same length")
    changed = [g for e, g in zip(expected, got, strict=True) if e != "same"]
    return sum(g == "same" for g in changed), len(changed)


def spread(values: Sequence[float]) -> tuple[float, float, float]:
    """(min, max, max - min). Empty input gives zeros."""
    if not values:
        return 0.0, 0.0, 0.0
    lo, hi = min(values), max(values)
    return lo, hi, hi - lo
