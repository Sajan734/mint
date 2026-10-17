"""Minimal COLMAP images.bin reader (struct only). Camera centre = -R^T t."""

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_POINT2D_BYTES = 24  # double x, double y, int64 point3D_id


@dataclass(frozen=True)
class ColmapImage:
    name: str
    qvec: tuple[float, float, float, float]  # w, x, y, z (world -> camera)
    tvec: tuple[float, float, float]

    @property
    def center(self) -> np.ndarray:
        return camera_center(self.qvec, self.tvec)


def quat_to_rot(q: tuple[float, float, float, float]) -> np.ndarray:
    w, x, y, z = (float(v) for v in q)
    n = w * w + x * x + y * y + z * z
    w, x, y, z = (v / np.sqrt(n) for v in (w, x, y, z))
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def camera_center(
    q: tuple[float, float, float, float], t: tuple[float, float, float]
) -> np.ndarray:
    return -quat_to_rot(q).T @ np.asarray(t, dtype=float)


def read_images_bin(path: Path) -> dict[str, ColmapImage]:
    """name -> ColmapImage. Raises ValueError on a truncated file."""
    data = Path(path).read_bytes()
    out: dict[str, ColmapImage] = {}
    try:
        (count,) = struct.unpack_from("<Q", data, 0)
        pos = 8
        for _ in range(count):
            vals = struct.unpack_from("<i4d3di", data, pos)
            pos += struct.calcsize("<i4d3di")
            end = data.index(b"\x00", pos)
            name = data[pos:end].decode("utf-8")
            pos = end + 1
            (n2d,) = struct.unpack_from("<Q", data, pos)
            pos += 8 + n2d * _POINT2D_BYTES
            out[name] = ColmapImage(name, tuple(vals[1:5]), tuple(vals[5:8]))
        if pos > len(data):
            raise ValueError("truncated")
    except (struct.error, ValueError) as e:
        raise ValueError(f"bad images.bin {path}: {e}") from e
    return out
