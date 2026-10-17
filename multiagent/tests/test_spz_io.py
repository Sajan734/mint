import numpy as np
import pytest

from buyer_agent.errors import AgentError
from buyer_agent.spz_io import load_spz_cloud

gsply = pytest.importorskip("gsply")


def make(tmp_path, n=100):
    rng = np.random.default_rng(0)
    q = rng.normal(size=(n, 4)).astype("f4")
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    data = gsply.GSData(
        rng.normal(size=(n, 3)).astype("f4"),
        np.log(rng.uniform(0.01, 0.05, (n, 3))).astype("f4"),
        q,
        rng.normal(size=n).astype("f4"),
        rng.uniform(-1, 1, (n, 3)).astype("f4"),
        np.zeros((n, 0, 3), "f4"),
    )
    path = tmp_path / "t.spz"
    gsply.write_spz(path, data)  # the library's own encoder
    return path, data


def test_roundtrip_matches_within_quantisation(tmp_path):
    path, data = make(tmp_path)
    cloud = load_spz_cloud(path, up_axis="+y")
    assert np.abs(cloud.points - data.means).max() < 1e-3
    assert cloud.opacity.min() >= 0 and cloud.opacity.max() <= 1
    assert cloud.color.shape == (100, 3) and cloud.scale.shape == (100,)


def test_up_axis_applied_and_garbage_rejected(tmp_path):
    path, data = make(tmp_path)
    flipped = load_spz_cloud(path, up_axis="-y")
    assert np.allclose(flipped.points[:, 1], -data.means[:, 1], atol=1e-3)
    bad = tmp_path / "bad.spz"
    bad.write_bytes(b"not spz at all")
    with pytest.raises(AgentError):
        load_spz_cloud(bad)
    with pytest.raises(AgentError):
        load_spz_cloud(tmp_path / "missing.spz")
