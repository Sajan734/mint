import struct
from pathlib import Path

import numpy as np
import pytest

from eval.colmap_bin import camera_center, quat_to_rot, read_images_bin


def write_images_bin(path: Path, cams: dict[str, tuple[float, float, float]]) -> None:
    """Identity-rotation cameras at the given centres (t = -c)."""
    out = struct.pack("<Q", len(cams))
    for i, (name, c) in enumerate(cams.items(), 1):
        out += struct.pack("<i4d3di", i, 1.0, 0.0, 0.0, 0.0, *(-v for v in c), 1)
        out += name.encode() + b"\x00" + struct.pack("<Q", 2)
        out += struct.pack("<ddq", 1.0, 2.0, -1) * 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)


def test_reads_colmap_images_bin_written_by_test(tmp_path):
    p = tmp_path / "images.bin"
    write_images_bin(p, {"a.JPG": (1.0, 2.0, 3.0), "b.JPG": (0.0, 0.0, 5.0)})
    reg = read_images_bin(p)
    assert list(reg) == ["a.JPG", "b.JPG"]
    assert np.allclose(reg["a.JPG"].center, (1, 2, 3))


def test_camera_center_formula():
    # 90 degrees about z: R = [[0,-1,0],[1,0,0],[0,0,1]], c = -R^T t
    q = (np.sqrt(0.5), 0.0, 0.0, np.sqrt(0.5))
    assert np.allclose(quat_to_rot(q), [[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    t = (1.0, 2.0, 3.0)
    assert np.allclose(camera_center(q, t), -quat_to_rot(q).T @ np.array(t))
    assert np.allclose(camera_center(q, t), (-2.0, 1.0, -3.0))


def test_truncated_file_rejected(tmp_path):
    p = tmp_path / "images.bin"
    write_images_bin(p, {"a.JPG": (0.0, 0.0, 0.0)})
    p.write_bytes(p.read_bytes()[:-10])
    with pytest.raises(ValueError):
        read_images_bin(p)


def test_colmap_bin_matches_pycolmap():
    pycolmap = pytest.importorskip("pycolmap")
    sparse = None
    for root in Path(__file__).resolve().parents:
        cand = root / "data" / "paslcd" / "Pots" / "Instance_1" / "sparse" / "0"
        if (cand / "cameras.bin").exists():
            sparse = cand
            break
    if sparse is None:
        pytest.skip("real PASLCD data not present")
    ours = read_images_bin(sparse / "images.bin")
    rec = pycolmap.Reconstruction(str(sparse))
    assert len(ours) == len(rec.images)
    for im in rec.images.values():
        assert np.allclose(ours[im.name].center, im.projection_center(), rtol=1e-6, atol=1e-6)
