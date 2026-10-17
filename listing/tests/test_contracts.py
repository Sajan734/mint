from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts import Baseline, Condition, Identity, ListingDraft, ReferencePrice, Views
from stages.match_gate import GateRaw

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

STUB_MODELS = {
    "render": Views,
    "identify": Identity,
    "baseline_lookup": Baseline,
    "match_gate": GateRaw,
    "listing_text": ListingDraft,
    "reference_price": ReferencePrice,
    "condition": Condition,
}


def identity(**overrides):
    fields = dict(category="headphones", brand="Sony", visible_text=["SONY"], search_query="Sony headphones", confidence=0.9)
    return Identity(**(fields | overrides))


def test_brand_backed_by_visible_text_passes():
    assert identity().brand == "Sony"


def test_brand_without_visible_text_is_rejected():
    with pytest.raises(ValidationError, match="not backed by visible_text"):
        identity(visible_text=["WH-1000XM4"])


def test_null_brand_needs_no_visible_text():
    assert identity(brand=None, visible_text=[]).brand is None


def test_not_found_baseline_and_unscored_match_are_valid():
    from contracts import MatchCheck

    Baseline(query="q", image_path=None, source="image_search", note="nothing found")
    MatchCheck(same_category=None, same_product=None, verdict="uncertain", reason="r")


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        Baseline(query="q", image_path="x.png", source="manual", surprise=1)


@pytest.mark.parametrize("stub", sorted(FIXTURES.glob("*/stubs/*.json")), ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_fixture_stub_validates(stub):
    STUB_MODELS[stub.stem].model_validate_json(stub.read_text(encoding="utf-8"))
