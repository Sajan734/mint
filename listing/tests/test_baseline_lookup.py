"""baseline_lookup: query priority, candidate decisions, search orchestration and manual mode. No real APIs."""

import asyncio
import json

import httpx
import pytest
from PIL import Image as PILImage

import stages.baseline_lookup as bl
from contracts import Identity, RunContext
from images import FittedImage
from stages.baseline_lookup import (
    THRESHOLDS,
    Candidate,
    SearchResult,
    baseline_query,
    choose_candidate,
    parse_results,
    prefilter,
)
from stages.identify import MissingKeyError


def remake(identity, update):
    """identity with `update` applied and validated again, so specificity and product_name follow (model_copy
    would keep the old ones)."""
    from contracts import Identity

    fields = {k: v for k, v in identity.model_dump().items() if k not in ("specificity", "product_name")}
    return Identity.model_validate(fields | update)


IDENTITY = Identity(
    category="in-ear headphones", brand="Sony", model=None, visible_text=["SONY"],
    search_query="Sony black in-ear headphones", confidence=0.9,
)


@pytest.mark.parametrize(
    "seller_name, expected",
    [
        ("Sony WI-XB400", "Sony WI-XB400"),  # the seller's product name wins over the identified query
        ("  Sony WI-XB400  ", "Sony WI-XB400"),
        (None, "Sony black in-ear headphones"),
        ("   ", "Sony black in-ear headphones"),
    ],
)
def test_seller_name_takes_priority(seller_name, expected):
    assert baseline_query(IDENTITY, seller_name) == expected


# --- decisions -------------------------------------------------------------------------------

GOOD = {"single_product": 0.95, "plain_background": 0.92, "matches_query": 0.90,
        "people_or_packaging": 0.04, "overlay_or_collage": 0.06}


def cand(position, **answers):
    return Candidate(SearchResult(position=position, image_url=f"https://x/{position}.jpg"), answers=GOOD | answers)


@pytest.mark.parametrize(
    "answers, passes",
    [
        ({}, True),
        ({"plain_background": 0.52}, False),  # noise around 0.5 never passes
        ({"plain_background": THRESHOLDS["yes_min"]}, True),
        ({"matches_query": 0.40}, False),
        ({"people_or_packaging": 0.48}, False),
        ({"overlay_or_collage": THRESHOLDS["no_max"]}, True),
        ({"overlay_or_collage": 0.35}, False),
    ],
)
def test_candidate_thresholds(answers, passes):
    assert (choose_candidate([cand(1, **answers)]) is not None) is passes


def test_best_weakest_criterion_wins():
    weaker = cand(1, plain_background=0.75)
    stronger = cand(2, plain_background=0.90)
    assert choose_candidate([weaker, stronger]) is stronger


def test_tie_goes_to_earlier_search_position():
    first, second = cand(1), cand(2)
    assert choose_candidate([second, first]) is first


def test_unchecked_candidates_are_never_chosen():
    assert choose_candidate([Candidate(SearchResult(1, "https://x/1.jpg"))]) is None


def test_parse_results_reads_serper_shape():
    payload = {"images": [
        {"title": "Sony WH-CH510", "imageUrl": "https://img.example/a.jpg", "imageWidth": 1200, "imageHeight": 1200,
         "link": "https://shop.example/p/1", "domain": "shop.example", "position": 1},
        {"title": "bad", "imageUrl": "data:image/png;base64,xx", "position": 2},
    ]}
    (r,) = parse_results(payload)
    assert (r.image_url, r.page_url, r.width, r.position) == ("https://img.example/a.jpg", "https://shop.example/p/1", 1200, 1)
    assert parse_results({}) == []


def test_prefilter_drops_small_and_odd_shapes_and_caps_count():
    results = [SearchResult(1, "u1", width=200, height=900), SearchResult(2, "u2", width=3000, height=600)]
    results += [SearchResult(i, f"u{i}", width=1000, height=1000) for i in range(3, 3 + bl.SEARCH["max_candidates"] + 2)]
    kept, dropped = prefilter(results)
    assert len(kept) == bl.SEARCH["max_candidates"]
    reasons = {c.result.position: c.problem for c in dropped}
    assert "too small" in reasons[1] and "aspect" in reasons[2]


# --- orchestration (network functions replaced) ----------------------------------------------


class FakeJev:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def offline(monkeypatch):
    """Replaces keys, Jev client, downloads and Jev checks. Tests set per-URL answers and search results."""
    state = {"queries": [], "results": {}, "answers": {}}
    monkeypatch.setattr(bl, "_require_key", lambda name: "test-key")
    monkeypatch.setattr(bl, "AsyncTypeSafeClient", FakeJev)

    async def search(query, key):
        state["queries"].append(query)
        result = state["results"].get(query, [])
        if isinstance(result, Exception):
            raise result
        return result

    async def fetch(client, c):
        c.image = FittedImage(b"jpegbytes", "image/jpeg", 800, 800)

    async def check(jev, query, c):
        c.answers = state["answers"][c.result.image_url]

    monkeypatch.setattr(bl, "search_images", search)
    monkeypatch.setattr(bl, "fetch_and_fit", fetch)
    monkeypatch.setattr(bl, "check_photo", check)
    return state


def results(*urls):
    return [SearchResult(i + 1, u, page_url=f"https://page/{i}", width=1000, height=1000) for i, u in enumerate(urls)]


def test_find_picks_best_candidate_and_saves_it(offline, tmp_path):
    offline["results"]["Sony WH-CH510 product photo"] = results("https://a", "https://b")
    offline["answers"] = {"https://a": GOOD | {"plain_background": 0.2}, "https://b": GOOD}
    baseline, log = asyncio.run(bl.find_baseline("Sony WH-CH510", tmp_path))
    assert baseline.source == "image_search" and baseline.source_url == "https://page/1"
    assert (tmp_path / "baseline.jpg").read_bytes() == b"jpegbytes"
    assert log["chosen"] == "https://b"
    assert offline["queries"] == ["Sony WH-CH510 product photo"]


def test_plain_query_is_tried_once_when_nothing_passes(offline, tmp_path):
    offline["results"]["q product photo"] = results("https://a")
    offline["results"]["q"] = results("https://b")
    offline["answers"] = {"https://a": GOOD | {"people_or_packaging": 0.9}, "https://b": GOOD}
    baseline, _ = asyncio.run(bl.find_baseline("q", tmp_path))
    assert offline["queries"] == ["q product photo", "q"]
    assert baseline.image_path is not None


def test_nothing_usable_gives_null_image_path(offline, tmp_path):
    offline["results"]["q product photo"] = results("https://a")
    offline["answers"] = {"https://a": GOOD | {"single_product": 0.1}}
    baseline, log = asyncio.run(bl.find_baseline("q", tmp_path))
    assert baseline.image_path is None
    assert "no search result passed" in baseline.note
    assert log["chosen"] is None and len(log["attempts"]) == 2


def test_search_errors_do_not_crash(offline, tmp_path):
    offline["results"]["q product photo"] = httpx.ConnectError("no network")
    offline["results"]["q"] = httpx.ConnectError("no network")
    baseline, _ = asyncio.run(bl.find_baseline("q", tmp_path))
    assert baseline.image_path is None
    assert "search failed" in baseline.note


def test_missing_serper_key_fails_early(monkeypatch, tmp_path):
    monkeypatch.setattr(bl, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="SERPER_API_KEY"):
        asyncio.run(bl.find_baseline("q", tmp_path))


# --- generic queries are not searched ----------------------------------------------------------


GENERIC = {"brand": None, "model": None, "visible_text": [], "search_query": "black in-ear headphones"}


@pytest.mark.parametrize(
    "update, seller_name, searches",
    [
        (GENERIC, None, False),  # colour + category only: would find some other product
        (GENERIC, "   ", False),
        ({**GENERIC, "visible_text": ["Made in China"]}, None, False),  # read text the query doesn't use
        (GENERIC, "Sony WI-XB400", True),  # the seller named it
        ({"model": "WI-XB400", "visible_text": ["SONY", "WI-XB400"]}, None, True),  # the model is printed on it
        ({"model": None}, None, True),  # the brand is printed on it
        # A product line read off the item: identify makes it the brand (real ThinkPad mouse scans in Supabase used
        # to go unsearched, so their match stayed uncertain).
        ({"category": "wireless mouse", "brand": "ThinkPad", "model": None, "visible_text": ["ThinkPad"],
          "search_query": "ThinkPad wireless mouse"}, None, True),
    ],
)
def test_search_only_when_the_product_is_named(update, seller_name, searches, monkeypatch, tmp_path):
    called = []

    async def fake_find(query, run_dir):
        called.append(query)
        return bl.Baseline(query=query, image_path=None, source="image_search", note="x"), {}

    monkeypatch.setattr(bl, "find_baseline", fake_find)
    identity = remake(IDENTITY, update)
    item = tmp_path / "item"
    item.mkdir()
    baseline = asyncio.run(bl.baseline_lookup(ctx_for(item, tmp_path, manual=False), identity, seller_name))
    assert bool(called) is searches
    if not searches:
        assert baseline.image_path is None and baseline.note == bl.NO_PRODUCT_NOTE


@pytest.mark.parametrize(
    "model, seller_name, claimed",
    [
        (None, None, False),  # brand only: the search was ours, nobody named the product
        (None, "  ", False),
        (None, "Sony WI-XB400", True),
        ("WI-XB400", None, False),  # printed on the item, but our reading of it can be wrong: not a claim
    ],
)
def test_has_claim(model, seller_name, claimed):
    identity = remake(IDENTITY, {"model": model, "visible_text": ["SONY", "WI-XB400"]})
    assert bl.has_claim(identity, seller_name) is claimed


# --- manual mode --------------------------------------------------------------------------------


def ctx_for(item_dir, tmp_path, manual=True):
    return RunContext(item_id=item_dir.name, item_dir=item_dir, run_dir=tmp_path / "runs",
                      cache_dir=tmp_path / "cache", manual_baseline=manual)


@pytest.fixture
def no_search(monkeypatch):
    async def fail(*a, **k):
        raise AssertionError("searched in manual mode")

    monkeypatch.setattr(bl, "find_baseline", fail)


def test_manual_baseline_used_without_search(no_search, tmp_path):
    item = tmp_path / "item"
    item.mkdir()
    PILImage.new("RGB", (900, 700), (250, 250, 250)).save(item / "baseline.jpg")
    (item / "baseline.json").write_text(json.dumps({"source_url": "https://maker.example/p"}))
    baseline = asyncio.run(bl.baseline_lookup(ctx_for(item, tmp_path), IDENTITY, "Sony WI-XB400"))
    assert baseline.source == "manual" and baseline.query == "Sony WI-XB400"
    assert baseline.image_path == str(item / "baseline.jpg")
    assert baseline.source_url == "https://maker.example/p"


def test_manual_baseline_too_large_is_fitted_into_runs(no_search, tmp_path):
    item = tmp_path / "item"
    item.mkdir()
    PILImage.new("RGB", (4000, 3000), (250, 250, 250)).save(item / "baseline.png")
    baseline = asyncio.run(bl.baseline_lookup(ctx_for(item, tmp_path), IDENTITY, None))
    assert baseline.image_path == str(tmp_path / "runs" / "baseline_manual.png")
    with PILImage.open(baseline.image_path) as img:
        assert max(img.size) == 1568
    assert "shrunk from 4000x3000" in baseline.note


def test_manual_baseline_missing_gives_null(no_search, tmp_path):
    item = tmp_path / "item"
    item.mkdir()
    baseline = asyncio.run(bl.baseline_lookup(ctx_for(item, tmp_path), IDENTITY, None))
    assert baseline.image_path is None and baseline.source == "manual"
    assert "baseline.jpg" in baseline.note


def test_manual_mode_wins_over_fixture_stub(no_search, tmp_path):
    item = tmp_path / "item"
    (item / "stubs").mkdir(parents=True)
    (item / "stubs" / "baseline_lookup.json").write_text(
        json.dumps({"query": "x", "image_path": "stub.png", "source": "manual"}))
    baseline = asyncio.run(bl.baseline_lookup(ctx_for(item, tmp_path), IDENTITY, None))
    assert baseline.image_path is None  # no manual photo: never falls back to the stub or search


def test_live_lookup_writes_candidate_log(offline, tmp_path):
    item = tmp_path / "item"
    item.mkdir()
    offline["results"]["Sony WI-XB400 product photo"] = results("https://a")
    offline["answers"] = {"https://a": GOOD}
    ctx = ctx_for(item, tmp_path, manual=False)
    baseline = asyncio.run(bl.baseline_lookup(ctx, IDENTITY, "Sony WI-XB400"))
    assert baseline.image_path is not None
    log = json.loads((ctx.run_dir / "baseline_candidates.json").read_text())
    assert log["chosen"] == "https://a"
    assert log["attempts"][0]["candidates"][0]["answers"] == GOOD
