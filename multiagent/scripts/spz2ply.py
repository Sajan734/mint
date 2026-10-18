"""SPZ (v2/v3, gzip) -> 3DGS binary PLY in numpy, mirroring gsplat/mintsplat/export.py from_spz + to_ply (RUB in, RUB out).

python multiagent/scripts/spz2ply.py in.spz out.ply
"""

import gzip
import io
import struct
import sys
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement


def decode(data: bytes) -> dict:
    raw = gzip.decompress(data)
    magic, version, n, sh_deg, frac, _flags, _ = struct.unpack_from("<IIIBBBB", raw, 0)
    assert magic == 0x5053474E, hex(magic)
    assert version in (2, 3), version
    off = 16
    take = lambda k: (np.frombuffer(raw, np.uint8, k, off), off + k)
    pos, off = take(n * 9)
    alpha, off = take(n)
    col, off = take(n * 3)
    scl, off = take(n * 3)
    rot, off = take(n * (4 if version == 3 else 3))
    n_sh = (sh_deg + 1) ** 2 - 1
    sh, off = take(n * n_sh * 3)
    assert off == len(raw), (off, len(raw))

    p = pos.reshape(n, 3, 3).astype(np.int32)
    fixed = p[..., 0] | (p[..., 1] << 8) | (p[..., 2] << 16)
    fixed = np.where(fixed & 0x800000, fixed - (1 << 24), fixed)
    means = fixed.astype(np.float32) / (1 << frac)

    a = np.clip(alpha.astype(np.float32) / 255, 1e-6, 1 - 1e-6)
    opac = np.log(a / (1 - a))
    sh0 = (col.reshape(n, 3).astype(np.float32) / 255 - 0.5) / 0.15
    scales = scl.reshape(n, 3).astype(np.float32) / 16 - 10

    if (
        version == 3
    ):  # smallest three: 2 bits largest index, then 3 x (9-bit magnitude + sign), i = 3..0
        r = rot.reshape(n, 4).astype(np.uint64)
        comp = r[:, 0] | (r[:, 1] << 8) | (r[:, 2] << 16) | (r[:, 3] << 24)
        largest = (comp >> 30).astype(np.int64)
        q = np.zeros((n, 4), np.float32)  # xyzw
        mask = np.uint64(511)
        for i in (3, 2, 1, 0):
            sel = largest != i
            mag = (comp & mask).astype(np.float32)
            neg = ((comp >> np.uint64(9)) & np.uint64(1)).astype(bool)
            val = np.sqrt(0.5) * mag / 511
            val = np.where(neg, -val, val)
            q[sel, i] = val[sel]
            comp = np.where(sel, comp >> np.uint64(10), comp)
        rest = np.clip(1 - (q**2).sum(1), 0, None)
        q[np.arange(n), largest] = np.sqrt(rest)
    else:
        xyz = rot.reshape(n, 3).astype(np.float32) / 127.5 - 1
        w = np.sqrt(np.clip(1 - (xyz**2).sum(1), 0, None))
        q = np.concatenate([xyz, w[:, None]], 1)
    quats = q[:, [3, 0, 1, 2]]  # wxyz, as gsplat
    shN = np.zeros((n, 15, 3), np.float32)
    if n_sh:
        shN[:, :n_sh] = (sh.reshape(n, n_sh, 3).astype(np.float32) - 128) / 128
    return {
        "means": means,
        "scales": scales,
        "quats": quats,
        "opacities": opac,
        "sh0": sh0,
        "shN": shN,
        "version": version,
        "sh_degree": sh_deg,
    }


def to_ply(p: dict) -> bytes:
    n = len(p["means"])
    shN = p["shN"].transpose(0, 2, 1).reshape(n, -1)  # channel-major, as in INRIA's format
    q = p["quats"] / np.linalg.norm(p["quats"], axis=1, keepdims=True)
    data = np.concatenate(
        [
            p["means"],
            np.zeros((n, 3), np.float32),
            p["sh0"],
            shN,
            p["opacities"][:, None],
            p["scales"],
            q,
        ],
        1,
    ).astype(np.float32)
    names = (
        ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
        + [f"f_rest_{i}" for i in range(shN.shape[1])]
        + ["opacity"]
        + [f"scale_{i}" for i in range(3)]
        + [f"rot_{i}" for i in range(4)]
    )
    arr = np.zeros(n, dtype=[(k, "f4") for k in names])
    for i, k in enumerate(names):
        arr[k] = data[:, i]
    buf = io.BytesIO()
    PlyData([PlyElement.describe(arr, "vertex")], text=False).write(buf)
    return buf.getvalue()


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    p = decode(Path(src).read_bytes())
    Path(dst).write_bytes(to_ply(p))
    m = p["means"]
    print(
        f"{src}: v{p['version']} sh{p['sh_degree']} n={len(m)} min={m.min(0).round(3)} max={m.max(0).round(3)} "
        f"opacity(sigmoid) median={np.median(1 / (1 + np.exp(-p['opacities']))):.2f}"
    )
