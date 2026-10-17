import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from buyer_agent.claims import FileClaimsProvider
from buyer_agent.listing_adapter import (
    GRADE_TO_SCORE,
    claims_from_listing,
    is_listing_format,
    load_listing_claims,
    parse_claims,
)

MOCK = Path(__file__).resolve().parent.parent / "mock"

# item01 shape: listing_text stub + condition stub combined, as finalize.py would emit it.
HEADPHONES = {
    "item_id": "item01",
    "title": "Sony WH-1000XM4 Wireless Noise-Cancelling Headphones (Black)",
    "description": (
        "Sony WH-1000XM4 over-ear wireless headphones in black. Industry-leading noise cancelling, "
        "up to 30 hours of battery life, touch controls on the right ear cup, and a foldable "
        "design for travel."
    ),
    "attributes": {
        "brand": "Sony",
        "model": "WH-1000XM4",
        "colour": "black",
        "type": "over-ear",
        "connectivity": "Bluetooth",
    },
    "tags": ["headphones", "sony", "noise-cancelling", "wireless", "over-ear"],
    "condition_grade": "light_wear",
    "condition_notes": [
        "2 views show a scuff: right, 10° above; back-right, 10° above.",
        "3 views show signs of wear: back, 10° above; back-left, 10° above.",
    ],
    "price_cad": 150,
    "price_justification": ["..."],
    "preview_images": ["a.png"],
    "viewer_url": None,
    "needs_seller_check": False,
    "seller_check_reasons": [],
}


def test_headphone_fixture_converts():
    c = claims_from_listing(HEADPHONES)
    assert (c.brand, c.model, c.category) == ("Sony", "WH-1000XM4", "over-ear")
    assert c.specs == {"colour": "black", "connectivity": "Bluetooth"}
    assert c.condition_grade == GRADE_TO_SCORE["light_wear"] == 7.5
    assert len(c.condition_notes) == 2
    assert c.accessories_included == []  # nothing explicitly stated
    assert c.price and (c.price.amount, c.price.currency) == (150, "CAD")


def test_pots_listing_file_loads_and_accessory_is_stated():
    c = load_listing_claims(MOCK / "listings" / "pots_listing.json")
    assert c.accessories_included == ["white plastic watering can"]
    assert c.price.amount == 30 and c.category == "houseplant collection"


def test_accessories_from_attribute_and_dedupe():
    d = HEADPHONES | {
        "attributes": {"accessories": "case, cable and the case"},
        "description": "Comes with a charger.",
    }
    assert claims_from_listing(d).accessories_included == ["case", "cable", "charger"]


def test_filler_note_dropped_and_grades_map():
    d = HEADPHONES | {"condition_notes": ["No defects stood out in any view."]}
    assert claims_from_listing(d).condition_notes == []
    for grade, score in GRADE_TO_SCORE.items():
        assert claims_from_listing(HEADPHONES | {"condition_grade": grade}).condition_grade == score


def test_invalid_listing_raises():
    with pytest.raises(ValidationError):
        claims_from_listing({"description": "no title"})
    with pytest.raises(ValidationError):
        claims_from_listing(HEADPHONES | {"condition_grade": "mint"})


def test_detect_and_parse_both_formats():
    native = json.loads((MOCK / "claims" / "pots_truthful.json").read_text())
    assert not is_listing_format(native) and is_listing_format(HEADPHONES)
    assert parse_claims(native).condition_grade == 8
    assert parse_claims(HEADPHONES).condition_grade == 7.5


def test_file_provider_reads_listing_format(tmp_path):
    (tmp_path / "hp.json").write_text(json.dumps(HEADPHONES), encoding="utf-8")
    assert FileClaimsProvider(tmp_path).get("hp").model == "WH-1000XM4"


def test_view_labels_stripped_from_notes_and_pass_allowlist():
    from buyer_agent.jev_prompts import claim_label
    from buyer_agent.listing_adapter import clean_note

    c = claims_from_listing(HEADPHONES)
    assert c.condition_notes == ["2 views show a scuff.", "3 views show signs of wear."]
    pots = load_listing_claims(MOCK / "listings" / "pots_listing.json")
    assert pots.condition_notes == [
        "2 views show scratches or scuffs.",
        "The back view shows stains or discolouration.",
    ]
    assert all(claim_label(n) for n in c.condition_notes + pots.condition_notes)
    assert clean_note("Scuff near the hinge (azimuth 90°) in v02 and view_03") == (
        "Scuff near the hinge in and"
    )
