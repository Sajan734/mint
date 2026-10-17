"""Safe loader for 3DGS `.ply` and `.splat` files (AM-17/AM-18). Never pickles, never trusts a header."""

from dataclasses import dataclass
from typing import BinaryIO, Literal

import numpy as np

from buyer_agent.align import Cloud
from buyer_agent.errors import AgentError, ErrorCode

SH_C0 = 0.28209479177387814
SPLAT_RECORD = 32
_PLY_TYPES = {
    "char": "i1", "uchar": "u1", "short": "i2", "ushort": "u2", "int": "i4", "uint": "u4",
    "float": "<f4", "double": "<f8", "int8": "i1", "uint8": "u1", "int16": "<i2",
    "uint16": "<u2", "int32": "<i4", "uint32": "<u4", "float32": "<f4", "float64": "<f8",
}  # fmt: skip


@dataclass(frozen=True)
class SplatLimits:
    max_file_bytes: int = 300 * 1024 * 1024
    max_header_bytes: int = 4096
    max_properties: int = 64
    max_points: int = 3_000_000
    max_ram_bytes: int = 300 * 1024 * 1024


def _bad(detail: str) -> AgentError:
    return AgentError(ErrorCode.SPLAT_UNREADABLE, detail)


def _parse_header(head: bytes, limits: SplatLimits) -> tuple[int, int, np.dtype]:
    """Return (header_len, vertex_count, row dtype). Header only; body untouched."""
    end = head.find(b"end_header\n")
    if end < 0 or end + 11 > limits.max_header_bytes:
        raise _bad("header missing or over cap")
    lines = head[:end].decode("ascii", errors="strict").split("\n")
    if lines[0].strip() != "ply" or lines[1].strip() != "format binary_little_endian 1.0":
        raise _bad("only binary_little_endian ply supported")
    count, fields = -1, []
    for line in lines[2:]:
        parts = line.split()
        if not parts or parts[0] in ("comment", "obj_info"):
            continue
        if parts[0] == "element":
            if len(parts) != 3 or parts[1] != "vertex" or count >= 0:
                raise _bad("only one vertex element supported")
            count = int(parts[2])
        elif parts[0] == "property" and count >= 0 and len(parts) == 3 and parts[1] in _PLY_TYPES:
            fields.append((parts[2], _PLY_TYPES[parts[1]]))
        else:
            raise _bad(f"unsupported header line: {line[:40]}")
        if len(fields) > limits.max_properties:
            raise _bad("too many properties")
    if not 0 < count <= limits.max_points or not fields:
        raise _bad("vertex count out of range")
    dtype = np.dtype(fields)
    if dtype.itemsize * count > limits.max_ram_bytes:
        raise _bad("body would exceed RAM cap")
    return end + 11, count, dtype


def _finite(*arrays: np.ndarray | None) -> None:
    for arr in arrays:
        if arr is not None and not np.isfinite(arr).all():
            raise _bad("non-finite values")


def _read_ply(fh: BinaryIO, size: int, limits: SplatLimits) -> Cloud:
    header_len, count, dtype = _parse_header(fh.read(limits.max_header_bytes), limits)
    if header_len + count * dtype.itemsize != size:
        raise _bad("size does not match header")
    fh.seek(header_len)
    body = fh.read(count * dtype.itemsize)
    if len(body) != count * dtype.itemsize:
        raise _bad("truncated file")
    rows = np.frombuffer(body, dtype=dtype)
    names = dtype.names or ()
    if not {"x", "y", "z"} <= set(names):
        raise _bad("no x/y/z")
    points = np.stack([rows[k] for k in "xyz"], axis=1).astype(np.float64)
    opacity = scale = color = None
    if "opacity" in names:
        raw = np.clip(rows["opacity"].astype(np.float64), -60, 60)
        opacity = 1.0 / (1.0 + np.exp(-raw))
    if all(f"scale_{i}" in names for i in range(3)):
        logs = np.stack([rows[f"scale_{i}"] for i in range(3)], axis=1).astype(np.float64)
        _finite(logs)
        scale = np.exp(np.clip(logs, -30, 10)).max(axis=1)
    if all(f"f_dc_{i}" in names for i in range(3)):
        dc = np.stack([rows[f"f_dc_{i}"] for i in range(3)], axis=1).astype(np.float64)
        _finite(dc)
        color = np.clip(0.5 + SH_C0 * dc, 0.0, 1.0)
    _finite(points, opacity)
    return Cloud(points, opacity, scale, color)


def _read_splat(fh: BinaryIO, size: int, limits: SplatLimits) -> Cloud:
    if size % SPLAT_RECORD or not 0 < size // SPLAT_RECORD <= limits.max_points:
        raise _bad("bad .splat size")
    body = fh.read(size)
    if len(body) != size:
        raise _bad("truncated file")
    rec = np.dtype([("pos", "<f4", 3), ("scale", "<f4", 3), ("rgba", "u1", 4), ("rot", "u1", 4)])
    rows = np.frombuffer(body, dtype=rec)
    points = rows["pos"].astype(np.float64)
    scale = rows["scale"].astype(np.float64).max(axis=1)
    _finite(points, scale)
    rgba = rows["rgba"].astype(np.float64) / 255.0
    return Cloud(points, rgba[:, 3], scale, rgba[:, :3])


def _orient(cloud: Cloud, up_axis: str) -> Cloud:
    if up_axis == "+y":
        return cloud
    x, y, z = cloud.points.T
    # "-y": 3DGS y-down -> flip Y and Z. "+z": rotate -90 deg about X (z becomes y).
    pts = np.stack([x, -y, -z] if up_axis == "-y" else [x, z, -y], axis=1)
    return Cloud(pts, cloud.opacity, cloud.scale, cloud.color)


def load_cloud(
    fh: BinaryIO,
    size: int,
    fmt: Literal["ply", "splat"],
    up_axis: Literal["-y", "+y", "+z"] = "-y",
    limits: SplatLimits | None = None,
) -> Cloud:
    """Parse an already-opened file (AM-17) into a +Y-up Cloud."""
    limits = limits or SplatLimits()
    if size <= 0 or size > limits.max_file_bytes:
        raise _bad("file size out of range")
    if up_axis not in ("-y", "+y", "+z"):
        raise AgentError(ErrorCode.INPUT_INVALID, f"bad up_axis {up_axis}")
    try:
        if fmt == "ply":
            cloud = _read_ply(fh, size, limits)
        elif fmt == "splat":
            cloud = _read_splat(fh, size, limits)
        else:
            raise AgentError(ErrorCode.INPUT_INVALID, f"bad format {fmt}")
    except (ValueError, UnicodeDecodeError, IndexError) as exc:
        raise _bad(f"parse error: {type(exc).__name__}") from exc
    return _orient(cloud, up_axis)
