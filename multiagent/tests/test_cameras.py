import numpy as np

from buyer_agent import cameras
from buyer_agent.cameras import VIEWS, camera_pose, fit_distance, project_extent


def test_twelve_views_and_labels_match_jevlab():
    assert len(VIEWS) == 12
    assert [v.el for v in VIEWS] == [10] * 8 + [40] * 4
    assert VIEWS[0].label == "front (azimuth 0°), 10° above"
    assert VIEWS[11].label == "front-left (azimuth 315°), 40° above"


def test_labels_unique_and_under_80_chars():
    labels = [v.label for v in VIEWS]
    assert len(set(labels)) == 12 and all(len(s) < 80 for s in labels)


def test_camera_looks_at_center():
    center = np.array([1.0, 2.0, 3.0])
    pos, rot = camera_pose(center, 0.5, 135, 40)
    cam = rot @ (center - pos)
    assert np.allclose(cam[:2], 0, atol=1e-9) and cam[2] < 0
    assert np.allclose(rot @ rot.T, np.eye(3)) and np.linalg.det(rot) > 0


def test_fit_fills_85pct_within_5pct():
    rng = np.random.default_rng(0)
    pts = rng.normal(size=(5000, 3))
    pts = pts / np.linalg.norm(pts, axis=1, keepdims=True) * 0.5
    for v in (VIEWS[0], VIEWS[9]):
        d = fit_distance(pts, np.zeros(3), 0.5, v.az, v.el)
        pos, rot = camera_pose(np.zeros(3), 0.5, v.az, v.el, d)
        extent = np.quantile(project_extent(pts, pos, rot), 0.99)
        assert abs(extent - cameras.FILL) < 0.05
