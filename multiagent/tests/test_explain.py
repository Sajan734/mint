import re

import pytest

from buyer_agent.advisor import draft
from buyer_agent.explain import build_explanation, how_sure
from buyer_agent.groq_client import GroqCallError
from buyer_agent.models import CategoryEvidence, ClaimsFinding, Evidence, Verdict
from buyer_agent.planner import Plan, plan
from tests.fakes_groq import FakeGroq
from tests.test_advisor import reply
from tests.test_judge import run, settings

BANNED = re.compile(
    r"\b(proven|definitely|guaranteed|price|paid|payment|pay|refunded)\b", re.IGNORECASE
)


def verdict(label="different", score=0.9, flagged=("part_diff",)):
    cats = {c: CategoryEvidence(evidence=0.9, max=0.9, views=["a", "b", "c"]) for c in flagged}
    ev = Evidence(
        requested_views=12, answered_views=12, usable_views=12, failed_views=[],
        categories=cats, flagged=list(flagged), alignment=None, alignment_mode="icp",
    )  # fmt: skip
    return Verdict(label=label, evidence_score=score, reason="r", evidence=ev, caveats=["c1"])


def finding(status, claim="red lid"):
    return ClaimsFinding(claim=claim, source="accessory", status=status, p_present=0.5, views=[])


def explain(v, findings=(), attempt=1, groq=None):
    p = plan(v, list(findings), attempt)
    step = run(
        draft(groq or FakeGroq([GroqCallError(False, "x")]), p, v, list(findings), None, settings())
    )
    return p, step, build_explanation(p, v, list(findings), step)


def texts(e):
    parts = [e.headline, e.what_we_compared, e.how_sure, e.friendly_summary or "", *e.what_we_found]
    return parts + e.listing_vs_item + e.what_to_do


@pytest.mark.parametrize(
    ("s", "word"), [(0.8, "fairly strong"), (0.79, "moderate"), (0.5, "moderate"), (0.49, "weak")]
)
def test_how_sure_bands(s, word):
    assert word in how_sure(s) and "not proof" in how_sure(s)


def test_found_and_claim_lines():
    v = verdict(flagged=("part_diff", "color_diff"))
    fs = [finding("supported"), finding("contradicted", "lid"), finding("unverifiable", "box")]
    _, _, e = explain(v, fs)
    assert e.what_we_found[0].startswith("A part or piece looks different or missing (in 3 of 12")
    assert "Colours look different" in e.what_we_found[1]
    assert e.listing_vs_item == [
        "Listing says red lid. We can see it.",
        "Listing says lid. We could not see it in your scan.",
        "Listing says box. We cannot check this from the scan.",
    ]


def test_refund_steps_and_message_from_evidence():
    p, step, e = explain(verdict())
    assert p.category == "request_refund" and 2 <= len(e.what_to_do) <= 5
    assert "marketplace" in e.what_to_do[0] and "return window" in e.what_to_do[-1]
    assert "part or piece" in step.refund_request and step.refund_request != "full refund"


def test_none_and_no_claims():
    _, _, e = explain(verdict("same", None, ()))
    assert e.what_to_do == ["Nothing to do. Keep your photos for your records."]
    assert e.listing_vs_item == [] and "no clear difference" in e.what_we_found[0]


def test_listing_rejected_steps():
    v = verdict("listing_rejected", None, ())
    p = plan(v, [], 1)
    step = run(draft(FakeGroq([]), p, v, [], None, settings()))
    e = build_explanation(p, v, [], step)
    assert "product check" in e.headline and any("support" in s for s in e.what_to_do)


@pytest.mark.parametrize(
    "v",
    [
        verdict("uncertain", 0.3, ()),
        verdict("scan_quality_poor", None, ()),
        verdict("different", 0.6),
    ],
)
def test_other_categories_have_steps(v):
    assert 1 <= len(explain(v)[2].what_to_do) <= 5


def test_groq_failure_falls_back_to_template_facts():
    _, step, e = explain(verdict())
    assert step.is_template and "likely" in e.friendly_summary


def test_groq_summary_used_when_valid():
    g = FakeGroq([reply(summary="The item appears to differ, so ask the seller.", cited_views=[])])
    p = Plan(category="message_seller", audience="seller", reason_code="R5", cited_views=[])
    v = verdict(score=0.5)
    step = run(draft(g, p, v, [], None, settings()))
    e = build_explanation(p, v, [], step)
    assert not step.is_template and e.friendly_summary == step.summary


@pytest.mark.parametrize("v", [verdict(), verdict("same", None, ()), verdict("different", 0.6)])
def test_no_banned_words(v):
    _, step, e = explain(v, [finding("contradicted")])
    assert not [t for t in [*texts(e), step.refund_request or ""] if BANNED.search(t)]


def test_claim_lines_strip_punct_and_note_wording():
    fs = [
        finding("supported", "red lid."),
        ClaimsFinding(
            claim="2 views show a scuff.", source="condition_note", status="unverifiable",
            p_present=None, views=[],
        ),
    ]  # fmt: skip
    lines = build_explanation(*_pieces(fs)).listing_vs_item
    assert lines[0] == "Listing says red lid. We can see it."
    assert lines[1] == (
        "The listing notes: 2 views show a scuff. We cannot check this from the scan."
    )
    assert not any(".." in x for x in lines)


def _pieces(fs):
    v = verdict()
    p, step, _ = explain(v, fs)
    return p, v, fs, step


def test_template_friendly_summary_is_not_headline_only():
    _, step, e = explain(verdict())
    assert step.is_template and e.friendly_summary != e.headline
    assert e.friendly_summary.startswith(e.headline) and "views" in e.friendly_summary
