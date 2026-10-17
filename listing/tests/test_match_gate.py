import pytest

from contracts import Baseline
from stages.match_gate import _GateScores, build_match_check, decide_verdict


@pytest.mark.parametrize(
    "same_category, same_product, expected",
    [
        (0.96, 0.91, "match"),
        (0.70, 0.70, "match"),
        (0.95, 0.08, "mismatch"),
        (0.10, 0.90, "mismatch"),
        (0.36, 0.36, "uncertain"),
        (0.95, 0.60, "uncertain"),
        # Run-to-run noise around 0.5 must not flip the verdict.
        (0.48, 0.48, "uncertain"),
        (0.52, 0.52, "uncertain"),
        (0.66, 0.74, "uncertain"),
        (0.74, 0.74, "match"),
        (0.31, 0.90, "mismatch"),
    ],
)
def test_decide_verdict(same_category, same_product, expected):
    assert decide_verdict(same_category, same_product) == expected


def test_reason_names_the_query():
    baseline = Baseline(query="Sony WH-1000XM4", image_path="x.png", source="manual")
    check = build_match_check(_GateScores(same_category=0.95, same_product=0.08), baseline)
    assert check.verdict == "mismatch"
    assert "Sony WH-1000XM4" in check.reason
