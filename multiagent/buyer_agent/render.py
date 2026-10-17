"""CPU point renderer: A and B seen through the same 12 cameras, as PNG pairs for Jev."""

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from buyer_agent import cameras
from buyer_agent.align import Cloud
from buyer_agent.cameras import SIZE, View
from buyer_agent.models import ViewPair

BACKGROUND = 0x80
MIN_OPACITY = 0.3
MAX_DISK = 6
FIT_SAMPLE = 20_000
CHUNK = 20_000
DEFAULT_COLOR = 0.78


def _disk_tables() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    offs, counts = [], [0]
    for r in range(1, MAX_DISK + 1):
        g = np.arange(-r, r + 1)
        dx, dy = np.meshgrid(g, g)
        m = dx * dx + dy * dy <= r * r
        offs.append(np.stack([dx[m], dy[m]], axis=1))
        counts.append(int(m.sum()))
    counts_a = np.array(counts)
    return np.concatenate(offs), counts_a, np.concatenate([[0], np.cumsum(counts_a[1:])])


_OFFS, _COUNTS, _STARTS = _disk_tables()  # index by radius 1..6 (starts shifted by one below)


@dataclass(frozen=True)
class Prepared:
    points: np.ndarray
    scale: np.ndarray
    color: np.ndarray


def _prepare(
    cloud: Cloud, matrix: np.ndarray | None, crop: dict, max_points: int, seed: int
) -> Prepared:
    pts = np.asarray(cloud.points, dtype=np.float64)
    n = len(pts)
    scale = np.ones(n) * 0.005 if cloud.scale is None else np.asarray(cloud.scale, np.float64)
    color = np.full((n, 3), DEFAULT_COLOR) if cloud.color is None else cloud.color
    keep = np.ones(n, bool) if cloud.opacity is None else cloud.opacity >= MIN_OPACITY
    if matrix is not None:
        s = float(abs(np.linalg.det(matrix[:3, :3]))) ** (1 / 3)
        pts, scale = pts @ matrix[:3, :3].T + matrix[:3, 3], scale * s
    keep &= np.linalg.norm(pts - np.asarray(crop["center"]), axis=1) <= float(crop["radius"])
    idx = np.flatnonzero(keep)
    if len(idx) > max_points:  # seeded subsample BEFORE any projection (AM-18)
        idx = np.sort(np.random.default_rng(seed).choice(idx, max_points, replace=False))
    return Prepared(pts[idx], scale[idx], np.asarray(color)[idx])


def _fragments(radius: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pixel offsets of every disk, point-major (so painter's order is preserved)."""
    counts = _COUNTS[radius]
    pt = np.repeat(np.arange(len(radius)), counts)
    first = np.cumsum(counts) - counts
    within = np.arange(counts.sum()) - np.repeat(first, counts)
    return pt, _OFFS[_STARTS[radius - 1][pt] + within]


def rasterise(prep: Prepared, pos: np.ndarray, rot: np.ndarray) -> np.ndarray:
    """Opaque z-buffered disks via far-to-near painter's order; last write wins."""
    img = np.full((SIZE * SIZE, 3), BACKGROUND, np.uint8)
    cam = (prep.points - pos) @ rot.T
    depth = -cam[:, 2]
    ok = depth > 1e-6
    f = (SIZE / 2) / np.tan(np.radians(cameras.FOV_DEG / 2))
    order = np.flatnonzero(ok)[np.argsort(-depth[ok], kind="stable")]
    d = depth[order]
    px = np.floor(SIZE / 2 + f * cam[order, 0] / d).astype(np.int64)
    py = np.floor(SIZE / 2 - f * cam[order, 1] / d).astype(np.int64)
    rad = np.clip(np.rint(prep.scale[order] * f / d), 1, MAX_DISK).astype(np.int64)
    rgb = (np.clip(prep.color[order], 0, 1) * 255).round().astype(np.uint8)
    for lo in range(0, len(order), CHUNK):
        sl = slice(lo, lo + CHUNK)
        pt, off = _fragments(rad[sl])
        x, y = px[sl][pt] + off[:, 0], py[sl][pt] + off[:, 1]
        inside = (x >= 0) & (x < SIZE) & (y >= 0) & (y < SIZE)
        img[(y * SIZE + x)[inside]] = rgb[sl][pt[inside]]
    return img.reshape(SIZE, SIZE, 3)


def _png(img: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img, "RGB").save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


class CpuPointRenderer:
    # ponytail: no alpha blending; upgrade = gsplat renderer
    def __init__(self, max_points: int = 300_000, seed: int = 0) -> None:
        self.max_points = max_points
        self.seed = seed

    def render(
        self, a: Cloud, b: Cloud, matrix, crop: dict, views: tuple[View, ...] = cameras.VIEWS
    ) -> list[ViewPair]:
        m = np.asarray(matrix, dtype=np.float64)
        pa = _prepare(a, None, crop, self.max_points, self.seed)
        pb = _prepare(b, m, crop, self.max_points, self.seed)
        center, radius = np.asarray(crop["center"], np.float64), float(crop["radius"])
        fit_pts = _fit_sample(pa.points, self.seed)
        pairs = []
        for v in views:
            dist = cameras.fit_distance(fit_pts, center, radius, v.az, v.el)
            pos, rot = cameras.camera_pose(center, radius, v.az, v.el, dist)
            pairs.append(
                ViewPair(
                    label=v.label,
                    azimuth_deg=v.az,
                    elevation_deg=v.el,
                    png_a=_png(rasterise(pa, pos, rot)),
                    png_b=_png(rasterise(pb, pos, rot)),
                )
            )
        return pairs


def _fit_sample(points: np.ndarray, seed: int) -> np.ndarray:
    if len(points) <= FIT_SAMPLE:
        return points
    return points[np.random.default_rng(seed).choice(len(points), FIT_SAMPLE, replace=False)]
