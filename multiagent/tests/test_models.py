import json
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from buyer_agent.errors import AgentError, ErrorCode, user_message
from buyer_agent.models import (
    CompareRequest,
    CompareResponse,
    ListingClaims,
    Prob,
    SplatRef,
    ViewFailure,
    ViewPair,
    ViewPairsRef,
    unique_labels,
)

SPLAT = SplatRef(path="a.ply", format="ply")
CID = "0b9e6c2a-3f43-4a3e-9a8e-6a1f3b2d9c11"
VIEW = "left (azimuth 90°), 10° above"
RESPONSE = {
    "v": 1,
    "comparison_id": CID,
    "status": "done",
    "verdict": {
        "label": "different",
        "evidence_score": 0.71,
        "reason": "Seen in 3 views: part_diff.",
        "evidence": {
            "requested_views": 12,
            "answered_views": 12,
            "usable_views": 10,
            "failed_views": [],
            "categories": {"part_diff": {"evidence": 0.68, "max": 0.83, "views": [VIEW]}},
            "flagged": ["part_diff"],
            "alignment": None,
            "alignment_mode": "skipped_view_pairs",
        },
        "caveats": ["Small dents and fine scratches may not show in 3D renders."],
    },
    "claims_available": True,
    "claims_findings": [
        {
            "claim": "watering can",
            "source": "accessory",
            "status": "contradicted",
            "p_present": 0.12,
            "views": [VIEW],
        }
    ],
    "next_step": {
        "category": "request_refund",
        "audience": "seller",
        "reason_code": "R4",
        "summary": "The item likely differs from the listing.",
        "message_to_seller": "Hi, ...",
        "refund_request": "I am requesting a refund because ...",
        "cited_views": [VIEW],
        "drafted_by": "groq:llama-3.3-70b-versatile",
        "is_template": False,
    },
    "error": None,
    "model_ids": {"jev": "jev-1.13.0", "groq": "llama-3.3-70b-versatile"},
    "timings_ms": {"resolve": 420, "judge": 4100, "total": 7900},
    "run_id": CID,
}


def _req(**kw):
    return CompareRequest(comparison_id=uuid4(), listing_id="pots-1", **kw)


def test_models_are_frozen_and_forbid_extra():
    ref = ViewPairsRef(manifest_path="x.json")
    with pytest.raises(ValidationError):
        ref.manifest_path = "y"
    with pytest.raises(ValidationError):
        ViewPairsRef(manifest_path="x.json", bogus=1)


def test_listing_claims_ignores_unknown_fields():
    assert ListingClaims(title="Pot", surprise=1).title == "Pot"


def test_prob_rejects_nan_inf_and_out_of_range():
    ta = TypeAdapter(Prob)
    for bad in (float("nan"), float("inf"), -0.1, 1.1):
        with pytest.raises(ValidationError):
            ta.validate_python(bad)


def test_compare_request_requires_exactly_one_mode():
    pairs = ViewPairsRef(manifest_path="p.json")
    assert _req(view_pairs=pairs)
    assert _req(listing_splat=SPLAT, buyer_splat=SPLAT)
    for kw in (
        {},
        {"listing_splat": SPLAT},
        {"listing_splat": SPLAT, "buyer_splat": SPLAT, "view_pairs": pairs},
    ):
        with pytest.raises(ValidationError):
            _req(**kw)


@pytest.mark.parametrize("bad", ["a/b", "..", "a.b", "", "x" * 65])
def test_listing_id_pattern_rejects_slash_and_dots(bad):
    with pytest.raises(ValidationError):
        CompareRequest(
            comparison_id=uuid4(), listing_id=bad, view_pairs=ViewPairsRef(manifest_path="p")
        )


def test_viewpair_bytes_excluded_from_dump_and_repr():
    vp = ViewPair(label="front", png_a=b"SECRETA", png_b=b"SECRETB")
    assert "png_a" not in vp.model_dump() and "SECRETA" not in repr(vp)


def test_response_example_validates():
    resp = CompareResponse.model_validate(RESPONSE)
    dump = resp.model_dump_json()
    assert "confidence" not in dump and "detail" not in dump
    assert resp.verdict.evidence.alignment_mode == "skipped_view_pairs"


def test_view_failure_has_no_detail():
    with pytest.raises(ValidationError):
        ViewFailure(view="a", code="JEV_TIMEOUT", detail="boom")


def test_labels_unique():
    unique_labels(["a", "b"])
    with pytest.raises(AgentError) as e:
        unique_labels(["a", "a"])
    assert e.value.code is ErrorCode.INPUT_INVALID
    bad = json.loads(json.dumps(RESPONSE))
    bad["verdict"]["evidence"]["failed_views"] = [{"view": "a", "code": "X"}] * 2
    with pytest.raises(AgentError):
        CompareResponse.model_validate(bad)


def test_every_error_code_has_plain_message():
    for code in ErrorCode:
        assert user_message(code).endswith(".")


def test_agent_error_str_has_no_detail():
    err = AgentError(ErrorCode.INTERNAL, "secret path C:/x")
    assert str(err) == "INTERNAL" and err.detail == "secret path C:/x"
