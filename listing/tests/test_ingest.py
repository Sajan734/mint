"""ingest.py: SPZ decoding against the reference library, PLY output, and item-folder layout (no network)."""

import gzip
import json
import struct
from pathlib import Path

import numpy as np
import pytest
import torch

import splat_render
from ingest import IngestError, decode_spz, ingest, public_url, to_ply

DATA = Path(__file__).parent / "data"
# 16 real Gaussians written by Niantic's reference encoder exactly as the splat job writes them (SPZ v3,
# SH degree 3, SH bits 6/5), and the same file decoded by the reference decoder.
REFERENCE = DATA / "spz_v3_reference.spz"
EXPECTED = DATA / "spz_v3_reference_expected.json"


def expected():
    return {k: np.asarray(v, np.float32) for k, v in json.loads(EXPECTED.read_text()).items()}


def test_decode_matches_reference_decoder():
    mine, ref = decode_spz(REFERENCE.read_bytes()), expected()
    assert mine["version"] == 3 and mine["sh_degree"] == 3
    for key in ("positions", "scales", "colors", "sh"):
        np.testing.assert_allclose(mine[key], ref[key], atol=1e-6)
    finite = np.isfinite(ref["alphas"])  # the reference returns +-inf logits for alpha bytes 0 and 255
    np.testing.assert_allclose(mine["alphas"][finite], ref["alphas"][finite], atol=1e-5)
    assert np.isfinite(mine["alphas"]).all()
    q, qr = mine["rotations"], ref["rotations"]
    assert np.minimum(np.abs(q - qr).max(1), np.abs(q + qr).max(1)).max() < 1e-6  # q and -q are the same rotation


def test_ply_loads_in_splat_render():
    cloud = decode_spz(REFERENCE.read_bytes())
    splat = splat_render.parse_ply(to_ply(cloud), torch.device("cpu"))
    np.testing.assert_allclose(splat.means.numpy(), cloud["positions"])
    np.testing.assert_allclose(splat.opacities.numpy(), 1 / (1 + np.exp(-cloud["alphas"])), atol=1e-6)
    w_first = np.concatenate([cloud["rotations"][:, 3:], cloud["rotations"][:, :3]], 1)  # PLY rot_0 is w
    norm = w_first / np.linalg.norm(w_first, axis=1, keepdims=True)
    np.testing.assert_allclose(splat.quats.numpy(), norm, atol=1e-6)


def spz_v2(position, alpha_byte, color_bytes, scale_bytes, rot_bytes):
    """One Gaussian, SH degree 0, version 2 (first-three quaternion), built by hand from the format."""
    fixed = [round(v * 4096) & 0xFFFFFF for v in position]
    pos = b"".join(f.to_bytes(3, "little") for f in fixed)
    header = struct.pack("<IIIBBBB", 0x5053474E, 2, 1, 0, 12, 0, 0)
    body = pos + bytes([alpha_byte]) + bytes(color_bytes) + bytes(scale_bytes) + bytes(rot_bytes)
    return gzip.compress(header + body)


def test_decode_version_2_by_hand():
    cloud = decode_spz(spz_v2((0.5, -1.25, 2.0), 191, (255, 128, 0), (160, 144, 128), (128, 128, 128)))
    np.testing.assert_allclose(cloud["positions"][0], [0.5, -1.25, 2.0])
    np.testing.assert_allclose(cloud["scales"][0], [0.0, -1.0, -2.0])
    np.testing.assert_allclose(cloud["alphas"][0], np.log(191 / 64), rtol=1e-5)
    np.testing.assert_allclose(cloud["colors"][0], [(1 - 0.5) / 0.15, (128 / 255 - 0.5) / 0.15, -0.5 / 0.15],
                               atol=1e-5)
    np.testing.assert_allclose(cloud["rotations"][0], [1 / 255, 1 / 255, 1 / 255, 1.0], atol=1e-4)
    assert cloud["sh"].shape == (1, 0, 3)


def test_rejects_non_spz_and_version_4():
    with pytest.raises(IngestError):
        decode_spz(b"definitely not a splat")
    with pytest.raises(IngestError, match="version 4"):
        decode_spz(struct.pack("<II", 0x5053474E, 4) + b"\0" * 24)


def test_ingest_writes_item_folder(tmp_path):
    base, scan = "https://example.test", "11111111-2222-3333-4444-555555555555"
    folder = public_url(f"views/{scan}", base)
    views = {"layout": "cube_top", "views": [{"name": "00_az000_el+45",
                                              "files": {"transparent": "00_az000_el+45.png",
                                                        "grey": "00_az000_el+45_grey.png"}}]}
    manifest = {"scan_id": scan, "splat_url": public_url(f"splats/{scan}.spz", base),
                "views_json_url": f"{folder}/views.json"}
    served = {
        public_url(f"splats/{scan}.json", base): json.dumps(manifest).encode(),
        manifest["splat_url"]: REFERENCE.read_bytes(),
        manifest["views_json_url"]: json.dumps(views).encode(),
        f"{folder}/00_az000_el+45.png": b"png-a",
        f"{folder}/00_az000_el+45_grey.png": b"png-b",
    }
    requested = []

    def fake_get(url):
        requested.append(url)
        return served[url]

    item = ingest(scan, "Logitech M185", root=tmp_path, base=base, get=fake_get)

    assert item == tmp_path / scan and sorted(requested) == sorted(served)
    inputs = json.loads((item / "input.json").read_text())
    assert inputs["seller_name"] == "Logitech M185" and inputs["up_axis"] == "+y"
    assert (item / "splat.spz").read_bytes() == REFERENCE.read_bytes()
    splat = splat_render.parse_ply((item / "splat.ply").read_bytes(), torch.device("cpu"))
    assert len(splat.means) == 16
    assert (item / "reference_views" / "00_az000_el+45_grey.png").read_bytes() == b"png-b"
    assert json.loads((item / "manifest.json").read_text())["scan_id"] == scan
    assert not (tmp_path / f".{scan}.partial").exists()


def test_reingest_replaces_the_item(tmp_path):
    base, scan = "https://example.test", "abc"
    manifest = {"scan_id": scan, "splat_url": public_url(f"splats/{scan}.spz", base)}
    served = {public_url(f"splats/{scan}.json", base): json.dumps(manifest).encode(),
              manifest["splat_url"]: REFERENCE.read_bytes()}
    (tmp_path / scan).mkdir()
    (tmp_path / scan / "stale.txt").write_text("old")
    item = ingest(scan, root=tmp_path, base=base, get=served.__getitem__)
    assert not (item / "stale.txt").exists() and (item / "splat.ply").is_file()
