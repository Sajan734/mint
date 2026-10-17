import pytest

from buyer_agent.models import (
    CategoryEvidence,
    ClaimsFinding,
    Evidence,
    Verdict,
)
from buyer_agent.planner import plan


def verdict(label, score=None, flagged=(), views=("front",)):
    cats = {c: CategoryEvidence(evidence=0.9, max=0.9, views=list(views)) for c in flagged}
    ev = Evidence(
        requested_views=12,
        answered_views=12,
        usable_views=12,
        failed_views=[],
        categories=cats,
        flagged=list(flagged),
        alignment=None,
        alignment_mode="icp",
    )
    return Verdict(label=label, evidence_score=score, reason="r", evidence=ev, caveats=[])


def finding(status="contradicted", source="accessory"):
    return ClaimsFinding(claim="c", source=source, status=status, p_present=0.1, views=["back"])


def got(v, findings=(), attempt=1):
    p = plan(v, list(findings), attempt)
    return p.reason_code, p.category, p.audience


@pytest.mark.parametrize(
    ("v", "findings", "attempt", "expected"),
    [
        (verdict("uncertain"), [], 2, ("R0", "escalate", "support")),
        (verdict("scan_quality_poor"), [], 1, ("R1", "request_more_photos", "buyer")),
        (verdict("alignment_failed"), [], 1, ("R2", "request_more_photos", "buyer")),
        (verdict("uncertain"), [], 1, ("R3", "request_more_photos", "seller")),
        (verdict("different", 0.8, ["part_diff"]), [], 1, ("R4", "request_refund", "seller")),
        (verdict("different", 0.8, ["color_diff"]), [], 1, ("R5", "message_seller", "seller")),
        (verdict("same", 0.9), [finding()], 1, ("R6", "message_seller", "seller")),
        (verdict("same", 0.9), [], 1, ("R7", "none", "none")),
        # edges
        (verdict("different", 0.7, ["shape_diff"]), [], 1, ("R4", "request_refund", "seller")),
        (verdict("different", 0.69, ["shape_diff"]), [], 1, ("R5", "message_seller", "seller")),
        (
            verdict("different", 0.9, ["color_diff"]),
            [finding(source="condition_note")],
            1,
            ("R5", "message_seller", "seller"),
        ),
        (
            verdict("different", 0.9, ["color_diff"]),
            [finding()],
            1,
            ("R4", "request_refund", "seller"),
        ),
    ],
)
def test_planner_rows(v, findings, attempt, expected):
    assert got(v, findings, attempt) == expected


def test_r0_attempt2_different_goes_to_r4_r5():
    assert got(verdict("different", 0.9, ["part_diff"]), attempt=3)[0] == "R4"
    assert got(verdict("different", 0.3, ["color_diff"]), attempt=2)[0] == "R5"
    assert got(verdict("same", 0.9), attempt=2)[0] == "R7"


@pytest.mark.parametrize("label", ["uncertain", "alignment_failed", "scan_quality_poor"])
def test_r0_for_each_escalating_label(label):
    assert got(verdict(label), attempt=2)[0] == "R0"
    assert got(verdict(label), attempt=1)[0] != "R0"


def test_planner_uses_evidence_score_field():
    assert got(verdict("different", None, ["part_diff"]))[0] == "R5"


def test_same_inputs_same_output_100_times():
    v = verdict("different", 0.8, ["part_diff", "shape_diff"], views=("a", "b"))
    first = plan(v, [finding()], 1)
    assert first.cited_views == ["a", "b"]
    assert all(plan(v, [finding()], 1) == first for _ in range(100))
