"""reference_price stage: plausibility, category defaults and the never-failing source chain. No Gemini calls."""

import asyncio
import json

import pytest

import stages.reference_price as rp
from contracts import Identity, ReferencePrice, RunContext
from gemini import GeminiReply
from pipeline import ROOT
from stages.identify import GEMINI, MissingKeyError
from stages.reference_price import CATEGORY_DEFAULTS, GENERIC_DEFAULT, PRICE_LOOKUP, category_default, plausible


@pytest.fixture(autouse=True)
def search_grounding_on(monkeypatch):
    """These tests cover the whole grounded -> ungrounded -> default chain, which runs once billing turns Search
    grounding on. Off (the free tier), only the ungrounded call is made: see test_gemini_model.py."""
    monkeypatch.setitem(GEMINI, "search_grounding", True)

SONY = Identity(
    category="on-ear wireless headphones",
    brand="SONY",
    model="WH-CH510",
    visible_text=["SONY", "WH-CH510"],
    attributes={"colour": "blue"},
    search_query="SONY WH-CH510 blue on-ear wireless headphones",
    confidence=0.9,
)
SOURCES = [{"uri": "https://example.test/a", "title": "bestbuy.ca", "domain": None},
           {"uri": "https://example.test/b", "title": "sony.ca", "domain": None},
           {"uri": "https://example.test/c", "title": "amazon.ca", "domain": None}]


@pytest.mark.parametrize(
    "category, label",
    [
        ("on-ear wireless headphones", "headphones"),
        ("wireless in-ear headphones", "earbuds"),
        ("true wireless earbuds", "earbuds"),
        ("wireless mouse", "computer mouse"),
        ("smartphone", "phone"),
        ("mechanical keyboard", "keyboard"),
        ("hiking backpack", "bag"),
    ],
)
def test_category_default_matches(category, label):
    found, amount, matched = category_default(category)
    assert (found, matched) == (label, True)
    assert amount > 0


def test_headphones_never_match_phone():
    assert category_default("over-ear headphones")[0] == "headphones"


def test_unknown_category_uses_generic_default():
    assert category_default("decorative ceramic vase") == (*GENERIC_DEFAULT, False)


def test_every_default_is_plausible_for_its_own_category():
    for keywords, label, amount in CATEGORY_DEFAULTS:
        assert plausible(amount, keywords[0]) is None, label


@pytest.mark.parametrize(
    "amount, category, ok",
    [
        (79.99, "on-ear wireless headphones", True),
        (0, "on-ear wireless headphones", False),  # Gemini's "don't know"
        (-10, "on-ear wireless headphones", False),
        (PRICE_LOOKUP["max_cad"] + 1, "decorative ceramic vase", False),
        (3000.0, "wireless mouse", False),  # far above the mouse default
        (3000.0, "decorative ceramic vase", True),  # no category bounds for the generic default
        (5.0, "laptop", False),  # far below the laptop default
        (float("nan"), "laptop", False),
        ("80", "on-ear wireless headphones", False),
        (None, "on-ear wireless headphones", False),
        (True, "on-ear wireless headphones", False),
    ],
)
def test_plausible(amount, category, ok):
    assert (plausible(amount, category) is None) is ok


def test_schema_lets_gemini_say_zero():
    schema = rp.response_schema()
    assert list(schema["properties"]) == ["amount_cad", "note"]
    assert "exclusiveMinimum" not in schema["properties"]["amount_cad"]


def fake_gemini(monkeypatch, answers):
    """answers[i] is (raw, grounding) or an exception, for the i-th call."""
    calls = []

    async def fake(contents, system_prompt, schema, *, tools=None, **kwargs):
        calls.append({"contents": contents, "grounded": bool(tools)})
        answer = answers[len(calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        raw, grounding = answer
        return GeminiReply(raw=raw, model="fake", latency_ms=1.0, grounding=grounding)

    monkeypatch.setattr(rp, "generate_json", fake)
    return calls


def look_up(identity=SONY, seller_name=None):
    return asyncio.run(rp.look_up(identity, seller_name))


def test_grounded_answer_wins(monkeypatch):
    calls = fake_gemini(monkeypatch, [({"amount_cad": 79.99, "note": "Sony WH-CH510 at Best Buy Canada."}, SOURCES)])
    price, log = look_up()
    assert price.amount_cad == 79.99 and price.basis == "new_retail"
    assert price.note.startswith("Search-grounded new price: Sony WH-CH510")
    assert "Sources: bestbuy.ca, sony.ca." in price.note  # capped at max_sources_in_note
    assert log["source"] == "search_grounded"
    assert len(calls) == 1 and calls[0]["grounded"]


def test_ungrounded_when_search_returned_no_sources(monkeypatch):
    calls = fake_gemini(monkeypatch, [({"amount_cad": 79.99, "note": "x"}, []), ({"amount_cad": 85.0, "note": "Typical price."}, [])])
    price, log = look_up()
    assert price.amount_cad == 85.0 and price.basis == "llm_estimate"
    assert price.note == "Model estimate, not looked up: Typical price."
    assert log["source"] == "model_estimate"
    assert "not grounded" in log["attempts"][0]["rejected"]
    assert [c["grounded"] for c in calls] == [True, False]


def test_implausible_grounded_amount_falls_through(monkeypatch):
    fake_gemini(monkeypatch, [({"amount_cad": 9000.0, "note": "x"}, SOURCES), ({"amount_cad": 80.0, "note": "y"}, [])])
    price, log = look_up()
    assert price.amount_cad == 80.0 and log["source"] == "model_estimate"
    assert "outside" in log["attempts"][0]["rejected"]


def test_category_default_when_both_lookups_fail(monkeypatch):
    fake_gemini(monkeypatch, [RuntimeError("429 RESOURCE_EXHAUSTED"), ({"amount_cad": 0, "note": "unknown"}, [])])
    price, log = look_up()
    label, amount, _ = category_default(SONY.category)
    assert price == ReferencePrice(amount_cad=amount, basis="llm_estimate",
                                   note=f"Category default for {label}; no price lookup succeeded.")
    assert log["source"] == "category_default"
    assert "429" in log["attempts"][0]["error"] and "outside" in log["attempts"][1]["rejected"]


def test_missing_key_falls_to_default(monkeypatch):
    fake_gemini(monkeypatch, [MissingKeyError("GEMINI_API_KEY is missing")] * 2)
    price, log = look_up()
    assert log["source"] == "category_default" and price.amount_cad > 0


def test_seller_name_is_the_product_looked_up(monkeypatch):
    calls = fake_gemini(monkeypatch, [({"amount_cad": 79.99, "note": "x"}, SOURCES)])
    _, log = look_up(seller_name="  Sony WH-CH510 Blue  ")
    assert log["query"] == "Sony WH-CH510 Blue" and log["seller_typed"] is True
    assert "The seller says the product is: Sony WH-CH510 Blue" in calls[0]["contents"]


def test_identity_query_without_seller_name(monkeypatch):
    calls = fake_gemini(monkeypatch, [({"amount_cad": 79.99, "note": "x"}, SOURCES)])
    _, log = look_up()
    assert log["query"] == SONY.search_query and log["seller_typed"] is False
    assert f"Product: {SONY.search_query}" in calls[0]["contents"]


def test_stage_writes_raw_log(tmp_path, monkeypatch):
    fake_gemini(monkeypatch, [({"amount_cad": 79.99, "note": "x"}, SOURCES)])
    item_dir = tmp_path / "item"
    item_dir.mkdir()
    ctx = RunContext(item_id="item", item_dir=item_dir, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    price = asyncio.run(rp.reference_price(ctx, SONY, None))
    log = json.loads((tmp_path / "runs" / "reference_price_raw.json").read_text())
    assert price.amount_cad == 79.99 and log["source"] == "search_grounded"


def test_fixture_stub_used_without_calling_gemini(tmp_path, monkeypatch):
    fake_gemini(monkeypatch, [])
    item_dir = ROOT / "fixtures" / "item01"
    ctx = RunContext(item_id="item01", item_dir=item_dir, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    result = asyncio.run(rp.reference_price(ctx, SONY, "Sony WH-1000XM4"))
    assert result == ReferencePrice.model_validate_json((item_dir / "stubs" / "reference_price.json").read_text())
