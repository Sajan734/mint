"""reference_price stage: plausibility, category defaults and the never-failing source chain. No Gemini calls."""

import asyncio
import json

import httpx
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
    assert "not grounded" in log["attempts"][1]["rejected"]
    assert [c["grounded"] for c in calls] == [True, False]


def test_implausible_grounded_amount_falls_through(monkeypatch):
    fake_gemini(monkeypatch, [({"amount_cad": 9000.0, "note": "x"}, SOURCES), ({"amount_cad": 80.0, "note": "y"}, [])])
    price, log = look_up()
    assert price.amount_cad == 80.0 and log["source"] == "model_estimate"
    assert "outside" in log["attempts"][1]["rejected"]


def test_category_default_when_both_lookups_fail(monkeypatch):
    fake_gemini(monkeypatch, [RuntimeError("429 RESOURCE_EXHAUSTED"), ({"amount_cad": 0, "note": "unknown"}, [])])
    price, log = look_up()
    label, amount, _ = category_default(SONY.category)
    assert price == ReferencePrice(amount_cad=amount, basis="llm_estimate",
                                   note=f"Category default for {label}; no price lookup succeeded.")
    assert log["source"] == "category_default"
    assert "429" in log["attempts"][1]["error"] and "outside" in log["attempts"][2]["rejected"]


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


# --- real listings (Serper shopping) ---------------------------------------------------------------

THINKPAD = Identity(category="wireless mouse", brand="ThinkPad", visible_text=["ThinkPad"],
                    attributes={"colour": "black"}, search_query="ThinkPad black wireless mouse", confidence=0.95)
SHOPPING = json.loads((ROOT / "tests" / "data" / "serper_shopping_thinkpad.json").read_text(encoding="utf-8"))
ESSENTIAL = (0, 4)  # "ThinkPad Essential Wireless Mouse 4x30m56887" (Lenovo $26.99) and 4x30m56888 ($36.73)


@pytest.mark.parametrize(
    "text, amount",
    [
        ("$26.99", 26.99),
        ("$1,299.00", 1299.0),
        ("CA$49.99", 49.99),
        ("C$ 49.99", 49.99),
        ("49.99 CAD", 49.99),
        ("26,99 $", 26.99),
        ("1 299,99 $", 1299.99),
        ("1 299,99 $", 1299.99),
        ("$5", 5.0),
    ],
)
def test_parse_cad(text, amount):
    assert rp.parse_cad(text) == (amount, None)


@pytest.mark.parametrize("text", [None, "", "US$26.99", "$26.99 USD", "€26,99", "£20", "26.99", "$"])
def test_parse_cad_rejects(text):
    value, problem = rp.parse_cad(text)
    assert value is None and problem


def shop(price, seller, index=0):
    return rp.ShopResult(index=index, title="x", seller=seller, price_text=f"${price}", url=None, price_cad=price)


@pytest.mark.parametrize(
    "listings, amount, kept",
    [
        ([shop(26.99, "Lenovo"), shop(36.98, "Walmart")], 31.98, 2),
        ([shop(30.0, "A"), shop(32.0, "B"), shop(34.0, "C"), shop(124.99, "D")], 32.0, 3),  # 124.99 is an outlier
        ([shop(30.0, "A"), shop(30.0, "A"), shop(40.0, "B")], 35.0, 2),  # the duplicate counts once
        ([shop(30.0, "A")], None, 1),  # one listing can't set the price
        ([shop(30.0, "A"), shop(32.0, "A")], None, 2),  # two listings, one seller
        ([shop(30.0, None), shop(32.0, None)], None, 2),  # unknown sellers don't count as different sellers
        ([shop(26.99, "A"), shop(63.63, "B")], None, 2),  # two that disagree: no telling which is off
        ([shop(30.0, "A"), shop(31.0, "B"), shop(100.0, "C")], 30.5, 2),  # three: the odd one out is dropped
        ([], None, 0),
    ],
)
def test_combine_listings(listings, amount, kept):
    got, rest, _outcome = rp.combine_listings(listings)
    assert got == amount and len(rest) == kept


ESSENTIAL_NAME = "Lenovo ThinkPad Essential Wireless Mouse 4x30m56887"


def fake_search(monkeypatch, payload=SHOPPING):
    queries = []

    async def search(query, api_key):
        queries.append(query)
        return payload

    monkeypatch.setattr(rp, "search_shopping", search)
    return queries


def pick(same=ESSENTIAL, n=20, not_new=()):
    return {"results": [{"index": i, "same_product": 0.9 if i in same else 0.1, "new_single_unit": i not in not_new}
                        for i in range(n)]}


def test_listings_price_from_real_results(monkeypatch):
    queries = fake_search(monkeypatch)
    calls = fake_gemini(monkeypatch, [(pick(), [])])
    price, log = look_up(THINKPAD)
    assert price.basis == "new_retail" and price.amount_cad == 31.86  # median of $26.99 and $36.73
    assert [(s.seller, s.price_cad) for s in price.sources] == [("Lenovo", 26.99),
                                                                (SHOPPING["shopping"][4]["source"], 36.73)]
    assert price.sources[0].title == ESSENTIAL_NAME and price.sources[0].url.startswith("https://")
    assert price.note.startswith("Median new price of 2 current listings in Canada (Lenovo, ")
    assert log["source"] == "serper_shopping"
    assert queries == ["ThinkPad wireless mouse"] and len(calls) == 1  # one search, one check, no estimate
    assert "0. Lenovo ThinkPad Essential Wireless Mouse 4x30m56887 | seller: Lenovo | $26.99" in calls[0]["contents"]


def test_bundles_and_used_listings_do_not_count(monkeypatch):
    fake_search(monkeypatch)
    fake_gemini(monkeypatch, [(pick(same=(0, 4, 10), not_new=(10,)), [])])  # 10: "ThinkPad X9 Essential Bundle"
    price, log = look_up(THINKPAD)
    assert price.amount_cad == 31.86
    results = log["attempts"][0]["results"]
    assert results[10]["problem"] == "not sold new on its own"
    assert results[1]["problem"].startswith("not this product")



@pytest.mark.parametrize(
    "scores, cut",
    [
        ([1.0, 1.0, 0.0], 0.70),  # a confident pick: the usual bar
        ([0.3, 0.3, 0.2, 0.0], 0.25),  # the same results scored low the next run: the top tier still counts
        ([0.75, 0.6], 0.65),  # just above the bar: the tier reaches down to 0.65
        ([0.1, 0.0], 0.25),  # nothing fits: the floor keeps everything out
        ([], 0.25),
    ],
)
def test_same_product_cut_follows_the_best_tier(scores, cut):
    assert rp.same_product_cut(scores) == pytest.approx(cut)


def test_low_but_consistent_scores_still_pick_the_product(monkeypatch):
    """Live run 4 on the ThinkPad mouse: the Essential listings scored 0.3, everything else 0.0-0.2."""
    fake_search(monkeypatch)
    raw = pick(same=ESSENTIAL)
    for entry in raw["results"]:
        entry["same_product"] = 0.3 if entry["index"] in ESSENTIAL else 0.0
    fake_gemini(monkeypatch, [(raw, [])])
    price, _ = look_up(THINKPAD)
    assert price.amount_cad == 31.86 and len(price.sources) == 2


def test_a_thin_top_tier_widens_to_the_line_when_no_model_is_printed(monkeypatch):
    """Live on Supabase scan 3368fe55: Gemini scored the ThinkPad USB-C Compact listing 1.0 and the rest of the
    ThinkPad line 0.5. One listing can't set a price; the line can."""
    fake_search(monkeypatch)
    raw = pick(same=())
    for entry in raw["results"]:
        entry["same_product"] = {2: 1.0, 0: 0.5, 4: 0.5, 1: 0.5}.get(entry["index"], 0.0)
    fake_gemini(monkeypatch, [(raw, [])])
    price, _ = look_up(THINKPAD)
    assert sorted(s.price_cad for s in price.sources) == [26.99, 36.73, 41.2, 47.38]


def test_a_printed_model_never_widens(monkeypatch):
    fake_search(monkeypatch)
    raw = pick(same=())
    for entry in raw["results"]:
        entry["same_product"] = {2: 1.0, 0: 0.5, 4: 0.5, 1: 0.5}.get(entry["index"], 0.0)
    fake_gemini(monkeypatch, [(raw, []), ({"amount_cad": 47.0, "note": "x"}, SOURCES)])
    named = THINKPAD.model_copy(update={"model": "4Y51D20848", "visible_text": ["ThinkPad", "4Y51D20848"]})
    _price, log = look_up(named)
    assert log["source"] == "search_grounded" and "only 1 matching listing" in log["attempts"][0]["rejected"]


def test_nothing_named_means_no_listings_price(monkeypatch):
    """Live on Supabase scan b458b7a0: nothing read off the item, so "computer mouse" priced any mouse."""
    queries = fake_search(monkeypatch)
    fake_gemini(monkeypatch, [({"amount_cad": 0, "note": "x"}, [])] * 2)
    generic = THINKPAD.model_copy(update={"brand": None, "visible_text": [], "search_query": "black computer mouse"})
    _price, log = look_up(generic)
    assert queries == [] and log["attempts"][0]["rejected"].startswith("nothing names the product")

def test_one_matching_listing_falls_back_to_the_estimate(monkeypatch):
    fake_search(monkeypatch)
    fake_gemini(monkeypatch, [(pick(same=(0,)), []), ({"amount_cad": 79.99, "note": "x"}, SOURCES)])
    price, log = look_up(THINKPAD)
    assert log["source"] == "search_grounded" and price.sources == []
    assert "only 1 matching listing" in log["attempts"][0]["rejected"]


def test_results_gemini_skipped_or_garbled_do_not_count(monkeypatch):
    queries = fake_search(monkeypatch)
    raw = {"results": [{"index": 0, "same_product": 0.9, "new_single_unit": True},
                                      {"index": 4, "same_product": 1.7, "new_single_unit": True}]}  # 1.7: ignored
    fake_gemini(monkeypatch, [(raw, []), ({"amount_cad": 0, "note": "x"}, []), ({"amount_cad": 0, "note": "x"}, [])])
    _price, log = look_up(THINKPAD)
    assert log["source"] == "category_default"
    assert log["attempts"][0]["results"][4]["problem"] == "not checked"
    assert len(queries) == 1


def test_unpriced_and_foreign_results_are_dropped_before_gemini():
    payload = {"shopping": [{"title": "A", "source": "S1", "price": "US$20.00"}, {"title": "B", "source": "S2"},
                            {"title": "C", "source": "S3", "price": "$9000.00"}, {"title": "D", "price": "$30.00"}]}
    results = rp.parse_results(payload, "wireless mouse")
    assert [r.problem is None for r in results] == [False, False, False, True]
    assert "not in Canadian dollars" in results[0].problem and "outside" in results[2].problem


def test_no_priced_results_skip_gemini(monkeypatch):
    fake_search(monkeypatch, {"shopping": [{"title": "A", "source": "S", "price": "US$30.00"}]})
    calls = fake_gemini(monkeypatch, [({"amount_cad": 0, "note": "x"}, [])] * 2)
    _price, log = look_up(THINKPAD)
    assert log["attempts"][0]["rejected"] == "no result with a usable CAD price"
    assert len(calls) == 2  # the grounded and ungrounded estimates, no pick


def test_missing_serper_key_falls_back(monkeypatch):
    def no_key(name):
        raise MissingKeyError(f"{name} is missing")

    monkeypatch.setattr(rp, "_require_key", no_key)
    fake_gemini(monkeypatch, [({"amount_cad": 79.99, "note": "x"}, SOURCES)])
    price, log = look_up()
    assert price.basis == "new_retail" and log["source"] == "search_grounded"
    assert "SERPER_API_KEY" in log["attempts"][0]["error"]


@pytest.mark.parametrize(
    "update, seller_name, expected",
    [
        ({}, None, "ThinkPad wireless mouse"),  # no colour: identify words it differently each run
        ({"brand": None}, None, "ThinkPad wireless mouse"),  # read text the brand rule dropped still names it
        ({"model": "MS-1", "visible_text": ["ThinkPad", "MS-1"], "search_query": "ThinkPad MS-1 black mouse"}, None,
         "ThinkPad MS-1 wireless mouse"),
        ({}, "  Lenovo ThinkPad Essential  ", "Lenovo ThinkPad Essential"),  # the seller's name wins
    ],
)
def test_price_query(update, seller_name, expected):
    assert rp.price_query(THINKPAD.model_copy(update=update), seller_name) == expected


@pytest.mark.parametrize(
    "update, seller_typed, says",
    [
        ({}, False, "No model is printed on the item and the seller didn't name one."),
        ({}, True, "The seller says the product is: q"),  # Gemini judges whether that names a model or a line
        ({"model": "MS-1", "visible_text": ["ThinkPad", "MS-1"]}, False, "The model is known: MS-1 is printed"),
    ],
)
def test_pick_prompt_says_whether_the_model_is_known(update, seller_typed, says):
    prompt = rp.pick_prompt(THINKPAD.model_copy(update=update), "q", seller_typed, [])
    assert says in prompt


def test_listings_raw_log_is_json(tmp_path, monkeypatch):
    fake_search(monkeypatch)
    fake_gemini(monkeypatch, [(pick(), [])])
    item_dir = tmp_path / "item"
    item_dir.mkdir()
    ctx = RunContext(item_id="item", item_dir=item_dir, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    price = asyncio.run(rp.reference_price(ctx, THINKPAD, None))
    log = json.loads((tmp_path / "runs" / "reference_price_raw.json").read_text(encoding="utf-8"))
    assert log["attempts"][0]["results"][0]["price_cad"] == 26.99 and len(price.sources) == 2


def test_a_slow_listings_search_falls_back_within_the_budget(monkeypatch):
    async def slow(query, api_key):
        await asyncio.sleep(1)
        return SHOPPING

    monkeypatch.setattr(rp, "search_shopping", slow)
    monkeypatch.setitem(rp.SERPER_PRICE, "budget_s", 0.05)
    fake_gemini(monkeypatch, [({"amount_cad": 79.99, "note": "x"}, SOURCES)])
    price, log = look_up(THINKPAD)
    assert log["source"] == "search_grounded" and "within" in log["attempts"][0]["error"]
