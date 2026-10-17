"""splat_render's lifting (lift_masks) and tinting (tint_splat). Scenes are built by hand from the PLY format, like
test_ingest builds SPZs; tinting is also checked on the real reference SPZ."""

import gzip
import io
import math
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image as PILImage

import splat_render

DATA = Path(__file__).parent / "data"
REFERENCE = DATA / "spz_v3_reference.spz"  # 16 real Gaussians, SH degree 3
CPU = torch.device("cpu")
GREY = (128, 128, 128)


def ply_bytes(rows: dict[str, np.ndarray]) -> bytes:
    """A binary little-endian 3DGS PLY with these float properties, in this order."""
    names = list(rows)
    n = len(rows[names[0]])
    header = (f"ply\nformat binary_little_endian 1.0\nelement vertex {n}\n"
              + "".join(f"property float {k}\n" for k in names) + "end_header\n")
    table = np.zeros(n, dtype=[(k, "<f4") for k in names])
    for k in names:
        table[k] = rows[k]
    return header.encode("ascii") + table.tobytes()


def gaussians(x, y, z, scale=0.06, opacity=0.99, extra=None) -> dict[str, np.ndarray]:
    n = len(x)
    rows = {"x": x, "y": y, "z": z, "f_dc_0": np.zeros(n), "f_dc_1": np.zeros(n), "f_dc_2": np.zeros(n),
            "opacity": np.full(n, math.log(opacity / (1 - opacity))),
            **{f"scale_{i}": np.full(n, math.log(scale)) for i in range(3)},
            "rot_0": np.ones(n), "rot_1": np.zeros(n), "rot_2": np.zeros(n), "rot_3": np.zeros(n)}
    return rows | (extra or {})


def two_sheets() -> tuple[bytes, np.ndarray]:
    """A front sheet at z=+0.5 hiding a back sheet at z=-0.5, both 1 x 1 and dense. Returns (ply, means)."""
    g = np.linspace(-0.5, 0.5, 11)
    xs, ys = (a.ravel() for a in np.meshgrid(g, g))
    x, y = np.concatenate([xs, xs]), np.concatenate([ys, ys])
    z = np.concatenate([np.full(len(xs), 0.5), np.full(len(xs), -0.5)])
    return ply_bytes(gaussians(x, y, z)), np.stack([x, y, z], 1)


# --- lift_masks -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lifted_sheets():
    ply, means = two_sheets()
    left_half = np.zeros((64, 64), np.uint8)
    left_half[:, :32] = 255  # the camera at azimuth 0 looks down -z, so image left is -x
    return splat_render.lift_masks(ply, "+y", [(0, 0)], [(0, left_half)], 64, GREY), means, ply


def test_lift_renders_exactly_the_render_stage_view(lifted_sheets):
    lifted, _, ply = lifted_sheets
    assert lifted["images"][0] == splat_render.render_pngs(ply, "+y", [(0, 0)], 64, GREY)[0]


def test_lift_marks_the_visible_gaussians_inside_the_mask(lifted_sheets):
    lifted, means, _ = lifted_sheets
    pos = means[lifted["ids"]]
    share = lifted["hit"][0] / np.maximum(lifted["seen"][0], 1e-9)
    front_left = (pos[:, 2] > 0) & (pos[:, 0] < -0.15) & (lifted["seen"][0] > 0.5)
    assert front_left.sum() >= 20
    assert share[front_left].min() > 0.9
    front_right = (pos[:, 2] > 0) & (pos[:, 0] > 0.15)
    assert not front_right.any() or share[front_right].max() < 0.1


def test_lift_never_puts_hidden_gaussians_on_the_surface(lifted_sheets):
    lifted, means, _ = lifted_sheets
    pos = means[lifted["ids"]]
    front, back = pos[:, 2] > 0, pos[:, 2] < 0
    gap, seen = lifted["depth_gap"][0], lifted["seen"][0]
    assert np.median(gap[front & (seen > 0.5)]) == pytest.approx(0.0, abs=0.02)
    assert (gap[back] > 0.5).all()  # a whole sheet behind the surface (1.0 deep, in framing radii)
    assert seen[back].sum() < 0.1 * seen[front].sum()


def test_lift_reports_item_area(lifted_sheets):
    lifted, _, _ = lifted_sheets
    assert lifted["gaussians"] == lifted["rendered"] == 242
    assert 0 < lifted["mask_item_px"][0] < lifted["item_px"][0] <= 64 * 64


def test_lift_handles_a_view_without_masks():
    """A searched view where nothing was boxed still reports what shows in it (evidence against a mark)."""
    ply, means = two_sheets()
    centre = np.zeros((64, 64), np.uint8)
    centre[24:40, 24:40] = 255
    lifted = splat_render.lift_masks(ply, "+y", [(0, 0), (0, 40)], [(1, centre)], 64, GREY)
    assert lifted["hit"].shape == (1, len(lifted["ids"])) and lifted["seen"].shape == (2, len(lifted["ids"]))
    front = means[lifted["ids"]][:, 2] > 0
    assert (lifted["seen"][0][front] > 0).any()  # the view without a mask still sees the marked Gaussians


def test_lift_rejects_masks_of_the_wrong_shape():
    ply, _ = two_sheets()
    with pytest.raises(splat_render.SplatError, match="shape"):
        splat_render.lift_masks(ply, "+y", [(0, 0)], [(0, np.zeros((32, 32), np.uint8))], 64, GREY)
    with pytest.raises(splat_render.SplatError, match="view index"):
        splat_render.lift_masks(ply, "+y", [(0, 0)], [(1, np.zeros((64, 64), np.uint8))], 64, GREY)


# --- tint_splat -------------------------------------------------------------------------------


def test_tint_spz_changes_only_the_chosen_gaussians():
    data = REFERENCE.read_bytes()
    out = splat_render.tint_splat(data, np.array([5, 2]), (1.0, 0.0, 0.0), 1.0)
    before, after = gzip.decompress(data), gzip.decompress(out)
    _, n, _, layout = splat_render._spz_layout(before)
    allowed = set()
    for stream in ("colors", "sh"):
        offset, size = layout[stream]
        allowed |= {offset + i * size + k for i in (2, 5) for k in range(size)}
    changed = np.nonzero(np.frombuffer(before, np.uint8) != np.frombuffer(after, np.uint8))[0]
    assert len(changed) and set(changed.tolist()) <= allowed

    old, new = splat_render.parse_spz(data, CPU), splat_render.parse_spz(out, CPU)
    np.testing.assert_allclose(new.colors[[2, 5]].numpy(), [[1, 0, 0], [1, 0, 0]], atol=0.01)
    keep = [i for i in range(n) if i not in (2, 5)]
    assert torch.equal(new.colors[keep], old.colors[keep])
    assert torch.equal(new.means, old.means) and torch.equal(new.opacities, old.opacities)
    offset, size = layout["sh"]
    sh = np.frombuffer(after, np.uint8, n * size, offset).reshape(n, size)
    assert (sh[[2, 5]] == 128).all()  # higher SH bands zeroed: the tint is the same from every side


def test_tint_blends_by_strength():
    data = REFERENCE.read_bytes()
    old = splat_render.parse_spz(data, CPU).colors[3].numpy()
    new = splat_render.parse_spz(splat_render.tint_splat(data, [3], (1.0, 0.0, 0.0), 0.5), CPU).colors[3].numpy()
    np.testing.assert_allclose(new, 0.5 * old + 0.5 * np.array([1.0, 0.0, 0.0]), atol=0.01)


def test_tint_ply_changes_only_the_chosen_rows():
    rest = {f"f_rest_{i}": np.array([0.1, 0.2, 0.3]) * (i + 1) for i in range(3)}
    data = ply_bytes(gaussians(np.array([0.0, 1.0, 2.0]), np.zeros(3), np.zeros(3), extra=rest))
    out = splat_render.tint_splat(data, np.array([1]), (1.0, 0.0, 0.0), 1.0)
    count, names, offset = splat_render._read_header(data)
    dtype = np.dtype([(n, "<f4") for n in names])
    before = np.frombuffer(data, dtype, count, offset)
    after = np.frombuffer(out, dtype, count, offset)
    assert out[:offset] == data[:offset]
    assert after[[0, 2]].tobytes() == before[[0, 2]].tobytes()
    colour = 0.5 + splat_render.SH_C0 * np.array([after[1][f"f_dc_{c}"] for c in range(3)])
    np.testing.assert_allclose(colour, [1.0, 0.0, 0.0], atol=1e-6)
    assert all(after[1][f"f_rest_{i}"] == 0 for i in range(3))


def test_tint_rejects_indices_outside_the_file():
    with pytest.raises(splat_render.SplatError, match="indices"):
        splat_render.tint_splat(REFERENCE.read_bytes(), [16], (1.0, 0.0, 0.0), 1.0)


def test_tint_output_is_deterministic():
    data = REFERENCE.read_bytes()
    assert splat_render.tint_splat(data, [1], (1, 0, 0), 0.8) == splat_render.tint_splat(data, [1], (1, 0, 0), 0.8)


def test_png_from_lift_is_a_valid_image(lifted_sheets):
    with PILImage.open(io.BytesIO(lifted_sheets[0]["images"][0])) as img:
        assert img.size == (64, 64)
