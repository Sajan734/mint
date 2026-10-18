from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts import Baseline, Condition, Identity, ListingDraft, ReferencePrice, Views, product_name
from stages.match_gate import GateRaw

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

STUB_MODELS = {
    "load_photos": Views,
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


@pytest.mark.parametrize(
    "brand, model, specificity, name",
    [
        ("Sony", "WH-1000XM4", "model", "Sony WH-1000XM4"),
        ("Sony", None, "brand", "Sony headphones"),
        (None, None, "type", "headphones"),
        ("ThinkPad", "ThinkPad Essential Wireless Mouse", "model", "ThinkPad Essential Wireless Mouse"),  # no repeat
    ],
)
def test_specificity_and_name_follow_from_the_fields(brand, model, specificity, name):
    ident = identity(brand=brand, model=model)
    assert ident.specificity == specificity and ident.product_name == name == product_name(brand, model, "headphones")


@pytest.mark.parametrize("brand, model, specificity", [("Sony", None, "model"), (None, None, "brand"),
                                                       ("Sony", "X1", "brand"), (None, "X1", "model")])
def test_specificity_must_fit_brand_and_model(brand, model, specificity):
    with pytest.raises(ValidationError):
        identity(brand=brand, model=model, specificity=specificity)


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


def test_price_sources_default_to_none_and_need_a_price():
    from contracts import PriceSource

    assert ReferencePrice(amount_cad=30, basis="llm_estimate", note="x").sources == []
    with pytest.raises(ValidationError):
        PriceSource(title="t", price_cad=0)


@pytest.mark.parametrize(
    "value, text, backed",
    [
        ("WH1000XM4", "SONY WH-1000XM4", True),  # punctuation and spacing don't matter
        ("Bang & Olufsen", "BANG&OLUFSEN", True),
        ("MX Master 3", "Logitech MX Master 3S", False),  # whole words only: 3S is another model
        ("Pad", "ThinkPad", False),
        ("ThinkPad", "Lenovo ThinkPad Essential Wireless Mouse", True),
        ("", "anything", False),
    ],
)
def test_backed_by_text_matches_whole_words(value, text, backed):
    from contracts import backed_by_text

    assert backed_by_text(value, [text]) is backed
