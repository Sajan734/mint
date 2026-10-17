import hashlib
import io
import time

import numpy as np
import pytest
from PIL import Image

from buyer_agent import cameras
from buyer_agent.align import Cloud
from buyer_agent.render import CpuPointRenderer

EYE = np.eye(4)


def shell(n, seed=0, radius=0.5, scale=0.004):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3))
    v = v / np.linalg.norm(v, axis=1, keepdims=True) * radius * (1 + 0.2 * np.sin(5 * v[:, :1]))
    return Cloud(v, np.ones(n), np.full(n, scale), rng.uniform(0.2, 1, size=(n, 3)))


CROP = {"center": [0.0, 0.0, 0.0], "radius": 0.7}


def px(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


def test_same_inputs_same_png_sha256():
    a = shell(3000)
    r = CpuPointRenderer()
    one = [
        hashlib.sha256(p.png_a).hexdigest() for p in r.render(a, a, EYE, CROP, cameras.VIEWS[:2])
    ]
    two = [
        hashlib.sha256(p.png_a).hexdigest() for p in r.render(a, a, EYE, CROP, cameras.VIEWS[:2])
    ]
    assert one == two


def test_background_is_808080_and_size_1024():
    pair = CpuPointRenderer().render(shell(2000), shell(2000), EYE, CROP, cameras.VIEWS[:1])[0]
    img = px(pair.png_a)
    assert img.shape == (1024, 1024, 3)
    assert tuple(img[0, 0]) == (128, 128, 128)


def test_object_fills_85pct_of_frame_within_5pct():
    a = shell(20000)
    img = px(CpuPointRenderer().render(a, a, EYE, CROP, cameras.VIEWS[:1])[0].png_a)
    ys, xs = np.nonzero((img != 128).any(axis=2))
    half = max(xs.max() - 512, 512 - xs.min(), ys.max() - 512, 512 - ys.min()) / 512
    assert 0.80 <= half <= 0.95  # 99th-pct fit at 0.85 plus disk radius and the last 1%


def test_b_identity_matrix_renders_same_as_a():
    a = shell(3000)
    pair = CpuPointRenderer().render(a, a, EYE, CROP, cameras.VIEWS[:3])
    assert all(p.png_a == p.png_b for p in pair)


def test_subsample_cap_respected_and_seeded():
    from buyer_agent.render import _prepare

    a = shell(5000)
    p1, p2 = (_prepare(a, None, CROP, 1000, 0) for _ in range(2))
    p3 = _prepare(a, None, CROP, 1000, 1)
    assert len(p1.points) == 1000 and np.array_equal(p1.points, p2.points)
    assert not np.array_equal(p1.points, p3.points)


def test_points_outside_crop_not_drawn():
    a = shell(3000)
    far = Cloud(np.vstack([a.points, [[5.0, 5.0, 5.0]] * 50]))
    far = Cloud(far.points, None, np.full(len(far.points), 0.004), None)
    near = Cloud(a.points, None, np.full(3000, 0.004), None)
    r = CpuPointRenderer()
    assert r.render(far, far, EYE, CROP, cameras.VIEWS[:1])[0].png_a == (
        r.render(near, near, EYE, CROP, cameras.VIEWS[:1])[0].png_a
    )


def test_translated_b_matrix_moves_content():
    a = shell(3000)
    shift = np.eye(4)
    shift[0, 3] = 0.2
    pair = CpuPointRenderer().render(a, a, shift, CROP, cameras.VIEWS[:1])[0]
    assert pair.png_a != pair.png_b


@pytest.mark.slow
def test_200k_points_12_views_under_20s():
    a = shell(200_000, scale=0.002)
    t0 = time.perf_counter()
    pairs = CpuPointRenderer().render(a, a, EYE, CROP, cameras.VIEWS)
    elapsed = time.perf_counter() - t0
    assert len(pairs) == 12 and elapsed <= 20
