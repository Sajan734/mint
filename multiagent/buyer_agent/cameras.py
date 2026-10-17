"""The 12-view layout, camera pose and 85% fill rule (ported from jev-lab static/app.js)."""

from dataclasses import dataclass

import numpy as np

SIZE = 1024
FOV_DEG = 40.0
FILL = 0.85
SIDES = {
    0: "front", 45: "front-right", 90: "right", 135: "back-right",
    180: "back", 225: "back-left", 270: "left", 315: "front-left",
}  # fmt: skip


@dataclass(frozen=True)
class View:
    az: int
    el: int

    @property
    def label(self) -> str:
        return f"{SIDES[self.az]} (azimuth {self.az}°), {self.el}° above"


VIEWS: tuple[View, ...] = (
    *(View(az, 10) for az in (0, 45, 90, 135, 180, 225, 270, 315)),
    *(View(az, 40) for az in (45, 135, 225, 315)),
)


def direction(az: float, el: float) -> np.ndarray:
    a, e = np.radians(az), np.radians(el)
    return np.array([np.sin(a) * np.cos(e), np.sin(e), np.cos(a) * np.cos(e)])


def base_distance(radius: float) -> float:
    return radius / np.sin(np.radians(FOV_DEG / 2)) * 1.05


def camera_pose(center: np.ndarray, radius: float, az: float, el: float, dist: float | None = None):
    """Return (position, R) with R rows = camera right, up, back (world-to-camera rotation)."""
    center = np.asarray(center, dtype=np.float64)
    back = direction(az, el)
    pos = center + (base_distance(radius) if dist is None else dist) * back
    right = np.cross([0.0, 1.0, 0.0], back)
    right /= np.linalg.norm(right)
    return pos, np.stack([right, np.cross(back, right), back])


def project_extent(points: np.ndarray, pos: np.ndarray, rot: np.ndarray) -> np.ndarray:
    """Normalised max(|x|,|y|) of each point in the camera's NDC (1.0 = frame edge)."""
    cam = (points - pos) @ rot.T
    depth = -cam[:, 2]
    t = np.tan(np.radians(FOV_DEG / 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        ext = np.maximum(np.abs(cam[:, 0]), np.abs(cam[:, 1])) / (depth * t)
    return np.where(depth > 1e-9, ext, np.inf)


def fit_distance(points: np.ndarray, center: np.ndarray, radius: float, az: float, el: float):
    """Dolly in up to 4 damped passes so the 99th-pct extent of `points` is FILL of the frame."""
    center = np.asarray(center, dtype=np.float64)
    dist = base_distance(radius)
    if len(points) < 50:
        return dist
    for i in range(4):
        pos, rot = camera_pose(center, radius, az, el, dist)
        extent = min(float(np.quantile(project_extent(points, pos, rot), 0.99)), 4.0)
        if abs(extent - FILL) < 0.03:
            break
        ratio = extent / FILL
        dist *= ratio if i == 0 else np.sqrt(ratio)
    return float(dist)
