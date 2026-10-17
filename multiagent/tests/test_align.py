"""Ported cases from jev-lab tests/test_align.py plus the buyer-agent guards."""

import numpy as np
import pytest

from buyer_agent.align import MIN_POINTS, Cloud, align, apply
from buyer_agent.errors import AgentError, ErrorCode


def lumpy(n=4000, seed=1) -> np.ndarray:
    """An asymmetric lumpy shell (no symmetry for ICP to confuse)."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    th, ph = np.arccos(v[:, 2]), np.arctan2(v[:, 1], v[:, 0])
    r = 1 + 0.35 * np.sin(3 * th) * np.cos(2 * ph) + 0.25 * np.cos(ph + 1) * np.sin(th)
    pts = v * r[:, None] * np.array([1.0, 0.7, 1.4])
    return pts + 0.3 * (v[:, :1] > 0.6) * np.array([0.8, 0.0, 0.0])


def similarity(seed=3, scale=1.3):
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    q *= np.sign(np.linalg.det(q))
    return scale * q, np.array([2.0, -1.0, 0.5])


def test_recapture_with_random_similarity_is_recovered():
    pts = lumpy()
    r, t = similarity()
    b_pts = (pts - t) @ np.linalg.inv(r).T  # b maps to a via apply: a = b @ r.T + t
    res = align(Cloud(pts), Cloud(b_pts))
    back = apply(res["matrix"], b_pts)
    assert np.median(np.linalg.norm(back - pts, axis=1)) < 0.05
    assert abs(res["scale"] - 1.3) < 0.03 * 1.3 or abs(res["scale"] - 1.0) < 0.03
    assert res["metrics"]["a_covered"] > 0.8
    assert res["metrics"]["ambiguity"] < 0.9


def test_missing_chunk_scale_recovered():
    pts = lumpy()
    r, t = similarity(seed=5, scale=1.0)
    b_pts = (pts - t) @ np.linalg.inv(r).T
    keep = pts[:, 0] < 0.9
    res = align(Cloud(pts), Cloud(b_pts[keep]))
    assert abs(res["scale"] - 1.0) < 0.05


def test_identity_for_same_scan_with_floaters():
    pts = lumpy(6000)
    floaters = np.random.default_rng(9).uniform(-30, 30, size=(500, 3))
    cloud = Cloud(np.vstack([pts, floaters]))
    res = align(cloud, cloud)
    assert res["crop"]["radius"] < 2.0
    assert np.allclose(res["matrix"], np.eye(4), atol=0.05)


def test_too_few_points_rejected():
    small = Cloud(lumpy(MIN_POINTS - 100))
    with pytest.raises(AgentError) as e:
        align(small, Cloud(lumpy()))
    assert e.value.code is ErrorCode.SCAN_TOO_SPARSE


def test_deterministic_with_seed():
    a, b = Cloud(lumpy()), Cloud(lumpy(seed=2))
    assert align(a, b, seed=4)["matrix"] == align(a, b, seed=4)["matrix"]
