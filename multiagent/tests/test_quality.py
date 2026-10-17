import numpy as np

from buyer_agent.align import Cloud
from buyer_agent.quality import precheck


def blob(n=1000, scale=1.0, seed=0):
    return Cloud(np.random.default_rng(seed).normal(size=(n, 3)) * scale)


def test_pass_returns_empty():
    assert precheck(blob(), blob(seed=1)) == []


def test_sparse_b_flags_scan_too_sparse():
    assert "scan_too_sparse_b" in precheck(blob(), blob(n=100))


def test_extent_ratio_out_of_range_flags():
    assert precheck(blob(), blob(scale=5)) == ["extent_ratio_out_of_range"]
    assert precheck(blob(), blob(scale=0.1)) == ["extent_ratio_out_of_range"]


def test_non_finite_flags():
    bad = blob()
    bad.points[0, 0] = np.nan
    assert "non_finite_a" in precheck(bad, blob())
