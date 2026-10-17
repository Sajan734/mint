import io
import struct

import numpy as np
import pytest
from plyfile import PlyData, PlyElement

from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.splat_io import SplatLimits, load_cloud


def write_ply(path, n=10, opacity=0.0, extra_props=0, x=None):
    names = [
        "x",
        "y",
        "z",
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
        "f_dc_0",
        "f_dc_1",
        "f_dc_2",
    ]
    names += [f"extra_{i}" for i in range(extra_props)]
    arr = np.zeros(n, dtype=[(k, "<f4") for k in names])
    arr["x"] = np.arange(n) if x is None else x
    arr["y"], arr["z"] = 1.0, 2.0
    arr["opacity"], arr["f_dc_0"] = opacity, 10.0
    arr["scale_0"], arr["scale_1"], arr["scale_2"] = np.log(0.1), np.log(0.05), np.log(0.02)
    PlyData([PlyElement.describe(arr, "vertex")]).write(str(path))
    return path.read_bytes()


def load(data, fmt="ply", up="+y", limits=None):
    return load_cloud(io.BytesIO(data), len(data), fmt, up, limits)


def code(data, **kw):
    with pytest.raises(AgentError) as e:
        load(data, **kw)
    return e.value.code


def test_ply_fields_converted_opacity_sigmoid_scale_exp_color_clamped(tmp_path):
    c = load(write_ply(tmp_path / "a.ply", opacity=0.0))
    assert np.allclose(c.opacity, 0.5)
    assert np.allclose(c.scale, 0.1, atol=1e-6)
    assert np.allclose(c.color[:, 0], 1.0) and np.allclose(c.color[:, 1], 0.5)


def test_ply_header_caps(tmp_path):
    good = write_ply(tmp_path / "a.ply")
    assert (
        code(good.replace(b"binary_little_endian", b"ascii" + b" " * 15))
        is ErrorCode.SPLAT_UNREADABLE
    )
    assert (
        code(good.replace(b"binary_little_endian", b"binary_big_endian" + b" " * 3))
        is ErrorCode.SPLAT_UNREADABLE
    )
    many = write_ply(tmp_path / "b.ply", extra_props=60)  # 70 properties
    assert code(many) is ErrorCode.SPLAT_UNREADABLE
    big_header = good.replace(b"end_header\n", b"comment " + b"x" * 5000 + b"\nend_header\n")
    assert code(big_header) is ErrorCode.SPLAT_UNREADABLE


def test_ply_peak_ram_capped(tmp_path):
    data = write_ply(tmp_path / "a.ply", n=100)
    assert code(data, limits=SplatLimits(max_ram_bytes=1000)) is ErrorCode.SPLAT_UNREADABLE


def test_vertex_count_over_cap_and_size_mismatch(tmp_path):
    data = write_ply(tmp_path / "a.ply", n=10)
    assert code(data, limits=SplatLimits(max_points=5)) is ErrorCode.SPLAT_UNREADABLE
    assert code(data + b"\0") is ErrorCode.SPLAT_UNREADABLE


def test_truncated_file_rejected(tmp_path):
    data = write_ply(tmp_path / "a.ply")
    assert code(data[:-8]) is ErrorCode.SPLAT_UNREADABLE


def test_nan_values_rejected(tmp_path):
    x = np.arange(10, dtype=np.float32)
    x[3] = np.nan
    assert code(write_ply(tmp_path / "a.ply", x=x)) is ErrorCode.SPLAT_UNREADABLE


def test_file_over_limit_rejected_before_read():
    class Boom(io.BytesIO):
        def read(self, *a):
            raise AssertionError("read")

    with pytest.raises(AgentError):
        load_cloud(Boom(), 400 * 1024 * 1024, "ply", "-y")


def splat_bytes(n=3):
    rec = struct.pack("<3f3f4B4B", 1, 2, 3, 0.1, 0.2, 0.3, 255, 128, 0, 255, 128, 128, 128, 255)
    return rec * n


def test_splat_32_byte_records_parsed():
    c = load(splat_bytes(3), "splat")
    assert c.points.shape == (3, 3) and np.allclose(c.points[0], [1, 2, 3])
    assert np.isclose(c.scale[0], 0.3, atol=1e-6) and np.isclose(c.opacity[0], 1.0)
    assert np.isclose(c.color[0, 1], 128 / 255)


def test_splat_size_not_multiple_of_32_rejected():
    assert code(splat_bytes(3) + b"\0", fmt="splat") is ErrorCode.SPLAT_UNREADABLE


def test_up_axis_minus_y_flips_y_and_z():
    c = load(splat_bytes(1), "splat", up="-y")
    assert np.allclose(c.points[0], [1, -2, -3])


def test_up_axis_plus_z_maps_z_to_y():
    c = load(splat_bytes(1), "splat", up="+z")
    assert np.allclose(c.points[0], [1, 3, -2])
