import hashlib

import pytest

from buyer_agent import jev_prompts as jp

CONTEXT_V2_SHA = "53d0518f96daf42a9bc510c930a8618de4e419abbccab97b08d0fa54825fe4c1"


def test_view_questions_ids_are_six():
    assert set(jp.QUESTIONS_V2) == {
        "viewpoint_match",
        "shape_diff",
        "part_diff",
        "color_diff",
        "any_diff",
        "scan_quality_ok",
    }


def test_context_v2_matches_jevlab_source():
    assert hashlib.sha256(jp.CONTEXT_V2.encode()).hexdigest() == CONTEXT_V2_SHA


@pytest.mark.parametrize(
    "text", ["x" * 101, "a <<b", "line\nbreak", "café", "tab\there", "", "   ", "a;b"]
)
def test_claim_labels_allowlisted(text):
    assert jp.claim_label(text) is None


def test_claim_label_accepts_clean_text():
    assert jp.claim_label("  Original box (2 cables), no scratches.  ") == (
        "Original box (2 cables), no scratches."
    )
    assert jp.claim_label("x" * 100) == "x" * 100


def test_claim_question_names_four_views():
    q = jp.claim_question("charger", "n0nce")
    assert all(f"`view_{i}`" in q.instructions for i in range(1, 5))
    assert "<<claim-n0nce>>charger<<claim-n0nce>>" in q.instructions
