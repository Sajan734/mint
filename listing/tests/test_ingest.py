"""Reading the splat job's .spz (splat_render.parse_spz) against the reference library, and ingest.py's item-folder
layout (no network)."""

import gzip
import json
import struct
from pathlib import Path

import numpy as np
import pytest
import torch

import splat_render
from ingest import IngestError, check_spz, ingest, public_url
from pipeline import resolve_item

DATA = Path(__file__).parent / "data"
# 16 real Gaussians written by Niantic's reference encoder exactly as the splat job writes them (SPZ v3,
# SH degree 3, SH bits 6/5), and the same file decoded by the reference decoder.
REFERENCE = DATA / "spz_v3_reference.spz"
EXPECTED = DATA / "spz_v3_reference_expected.json"
CPU = torch.device("cpu")


def expected():
    return {k: np.asarray(v, np.float32) for k, v in json.loads(EXPECTED.read_text()).items()}


def test_spz_matches_reference_decoder():
    splat, ref = splat_render.parse_spz(REFERENCE.read_bytes(), CPU), expected()
    np.testing.assert_allclose(splat.means.numpy(), ref["positions"], atol=1e-6)
    np.testing.assert_allclose(splat.scales.numpy(), np.exp(ref["scales"]), rtol=1e-6)
    # the reference returns +-inf logits for alpha bytes 255 and 0; sigmoid maps them to 1 and 0
    np.testing.assert_allclose(splat.opacities.numpy(), 1 / (1 + np.exp(-ref["alphas"])), atol=1e-6)
    rgb = np.clip(0.5 + splat_render.SH_C0 * ref["colors"], 0.0, 1.0)
    np.testing.assert_allclose(splat.colors.numpy(), rgb, atol=1e-6)
    w_first = np.concatenate([ref["rotations"][:, 3:], ref["rotations"][:, :3]], 1)
    qr, q = w_first / np.linalg.norm(w_first, axis=1, keepdims=True), splat.quats.numpy()
    assert np.minimum(np.abs(q - qr).max(1), np.abs(q + qr).max(1)).max() < 1e-6  # q and -q are the same rotation


def spz_v2(position, alpha_byte, color_bytes, scale_bytes, rot_bytes):
    """One Gaussian, SH degree 0, version 2 (first-three quaternion), built by hand from the format."""
    fixed = [round(v * 4096) & 0xFFFFFF for v in position]
    pos = b"".join(f.to_bytes(3, "little") for f in fixed)
    header = struct.pack("<IIIBBBB", 0x5053474E, 2, 1, 0, 12, 0, 0)
    body = pos + bytes([alpha_byte]) + bytes(color_bytes) + bytes(scale_bytes) + bytes(rot_bytes)
    return gzip.compress(header + body)


def test_spz_version_2_by_hand():
    splat = splat_render.parse_spz(spz_v2((0.5, -1.25, 2.0), 191, (255, 128, 0), (160, 144, 128), (128, 128, 128)),
                                   CPU)
    np.testing.assert_allclose(splat.means[0].numpy(), [0.5, -1.25, 2.0])
    np.testing.assert_allclose(splat.scales[0].numpy(), np.exp([0.0, -1.0, -2.0]), rtol=1e-6)
    np.testing.assert_allclose(splat.opacities[0].item(), 191 / 255, atol=1e-6)
    dc = np.array([(1 - 0.5) / 0.15, (128 / 255 - 0.5) / 0.15, -0.5 / 0.15])
    np.testing.assert_allclose(splat.colors[0].numpy(), np.clip(0.5 + splat_render.SH_C0 * dc, 0, 1), atol=1e-6)
    np.testing.assert_allclose(splat.quats[0].numpy(), [1.0, 1 / 255, 1 / 255, 1 / 255], atol=1e-4)  # w x y z


def test_parse_splat_tells_spz_from_ply():
    assert len(splat_render.parse_splat(REFERENCE.read_bytes(), CPU).means) == 16
    with pytest.raises(splat_render.SplatError, match="not a PLY"):
        splat_render.parse_splat(b"definitely not a splat", CPU)


def test_rejects_non_spz_truncated_and_version_4():
    with pytest.raises(splat_render.SplatError, match="neither"):
        splat_render.parse_spz(b"definitely not a splat", CPU)
    with pytest.raises(splat_render.SplatError, match="version 4"):
        splat_render.parse_spz(struct.pack("<II", 0x5053474E, 4) + b"\0" * 24, CPU)
    with pytest.raises(splat_render.SplatError, match="truncated"):
        splat_render.parse_spz(gzip.compress(gzip.decompress(REFERENCE.read_bytes())[:-10]), CPU)
    with pytest.raises(IngestError, match="bad splat"):
        check_spz(b"definitely not a splat")
    assert check_spz(REFERENCE.read_bytes()) == 16


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
    assert not list(item.glob("*.ply"))  # only the .spz is kept
    assert resolve_item(item) == (item, item / "splat.spz")  # what pipeline.py renders
    assert (item / "reference_views" / "00_az000_el+45_grey.png").read_bytes() == b"png-b"
    assert json.loads((item / "manifest.json").read_text())["scan_id"] == scan
    assert not (tmp_path / f".{scan}.partial").exists()


def test_ingest_rejects_a_bad_splat_without_writing(tmp_path):
    base, scan = "https://example.test", "bad"
    manifest = {"scan_id": scan, "splat_url": public_url(f"splats/{scan}.spz", base)}
    served = {public_url(f"splats/{scan}.json", base): json.dumps(manifest).encode(),
              manifest["splat_url"]: b"<html>not a splat</html>"}
    with pytest.raises(IngestError, match="bad splat"):
        ingest(scan, root=tmp_path, base=base, get=served.__getitem__)
    assert not any(tmp_path.iterdir())


def test_reingest_replaces_the_item(tmp_path):
    base, scan = "https://example.test", "abc"
    manifest = {"scan_id": scan, "splat_url": public_url(f"splats/{scan}.spz", base)}
    served = {public_url(f"splats/{scan}.json", base): json.dumps(manifest).encode(),
              manifest["splat_url"]: REFERENCE.read_bytes()}
    (tmp_path / scan).mkdir()
    (tmp_path / scan / "stale.txt").write_text("old")
    item = ingest(scan, root=tmp_path, base=base, get=served.__getitem__)
    assert not (item / "stale.txt").exists() and (item / "splat.spz").is_file()


def test_resolve_item_still_takes_a_ply_folder(tmp_path):
    (tmp_path / "splat.ply").write_bytes(b"ply")
    assert resolve_item(tmp_path) == (tmp_path, tmp_path / "splat.ply")
    assert resolve_item(tmp_path / "x.spz") == (tmp_path, tmp_path / "x.spz")
