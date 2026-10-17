"""Pre-alignment code gate: cheap checks before spending time on ICP."""

from dataclasses import dataclass

import numpy as np

from buyer_agent.align import MIN_POINTS, Cloud


@dataclass(frozen=True)
class QualityLimits:
    min_points: int = MIN_POINTS
    ratio_min: float = 0.33
    ratio_max: float = 3.0


def _extent(points: np.ndarray) -> float:
    lo, hi = np.percentile(points, [2, 98], axis=0)
    return float(np.linalg.norm(hi - lo))


def precheck(a: Cloud, b: Cloud, limits: QualityLimits | None = None) -> list[str]:
    """Return problem codes; an empty list means pass."""
    limits = limits or QualityLimits()
    issues: list[str] = []
    for name, cloud in (("a", a), ("b", b)):
        if not np.isfinite(cloud.points).all():
            issues.append(f"non_finite_{name}")
        if len(cloud.points) < limits.min_points:
            issues.append(f"scan_too_sparse_{name}")
    if issues:
        return issues
    ea, eb = _extent(a.points), _extent(b.points)
    if ea <= 0 or not limits.ratio_min <= eb / ea <= limits.ratio_max:
        issues.append("extent_ratio_out_of_range")
    return issues
