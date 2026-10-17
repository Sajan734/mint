import asyncio
import json
import shutil
from pathlib import Path

import pytest

import cache
from contracts import Listing, RunContext, Views
from pipeline import run_pipeline, run_stage

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def run(item_dir, tmp_path, **kwargs):
    return asyncio.run(
        run_pipeline(item_dir, runs_root=tmp_path / "runs", cache_root=tmp_path / "cache", demo_mode=False, **kwargs)
    )


def test_item01_gives_listing(tmp_path):
    result = run(FIXTURES / "item01", tmp_path)
    expected = json.loads((FIXTURES / "item01" / "expected.json").read_text(encoding="utf-8"))
    assert isinstance(result, Listing)
    assert result.condition_grade == expected["condition_grade"]
    assert result.price_cad == expected["price_cad"]
    assert result.needs_seller_check is expected["needs_seller_check"]
    assert result.deal_rating.rating == expected["deal_rating"]
    assert result.deal_rating.asking_price_source == "suggested"
    assert result.highlight.status == expected["highlight_status"]
    written = {p.stem for p in (tmp_path / "runs" / "item01").glob("*.json")}
    assert written == {
        "render", "identify", "baseline_lookup", "match_gate", "listing_text", "reference_price", "condition",
        "highlight", "deal_rating", "finalize", "result", "timings",
    }
    saved = json.loads((tmp_path / "runs" / "item01" / "result.json").read_text(encoding="utf-8"))
    assert saved["deal_rating"]["rating"] == "fair" and saved["highlight"]["status"] == "skipped"


def test_item02_gives_rejection(tmp_path):
    result = run(FIXTURES / "item02", tmp_path)
    assert type(result).__name__ == "Rejection"
    assert result.match_check.verdict == "mismatch"
    assert "Sony WH-1000XM4" in result.match_check.reason  # the seller's name from input.json
    for stage in ("finalize", "highlight", "deal_rating"):
        assert not (tmp_path / "runs" / "item02" / f"{stage}.json").exists()


def test_highlight_failure_still_gives_listing(tmp_path, monkeypatch):
    import pipeline

    async def broken(ctx, *args):
        raise RuntimeError("Modal app isn't deployed")

    monkeypatch.setattr(pipeline, "highlight", broken)
    result = run(FIXTURES / "item01", tmp_path)
    assert isinstance(result, Listing)
    assert result.highlight.status == "failed" and result.highlight.splat_path is None
    assert "RuntimeError: Modal app isn't deployed" in result.highlight.summary
    saved = json.loads((tmp_path / "runs" / "item01" / "highlight.json").read_text(encoding="utf-8"))
    assert saved["status"] == "failed"


def test_highlight_failure_is_not_cached(tmp_path, monkeypatch):
    import pipeline

    async def broken(ctx, *args):
        raise RuntimeError("Gemini is down")

    monkeypatch.setattr(pipeline, "highlight", broken)
    asyncio.run(run_pipeline(FIXTURES / "item01", runs_root=tmp_path / "runs", cache_root=tmp_path / "cache",
                             demo_mode=True))
    assert not (tmp_path / "cache" / "item01" / "highlight.json").exists()


def demo_run(tmp_path, item=FIXTURES / "item01", **kwargs):
    return asyncio.run(run_pipeline(item, runs_root=tmp_path / "runs", cache_root=tmp_path / "cache",
                                    **({"demo_mode": True} | kwargs)))


def cached_stages(tmp_path, item_id="item01"):
    """{stage: number of cache entries}; entries are <stage>.<key>.json."""
    stages = [p.name.split(".")[0] for p in (tmp_path / "cache" / item_id).glob("*.json")]
    return {s: stages.count(s) for s in stages}


def test_cached_highlight_with_missing_file_is_reported(tmp_path):
    from contracts import Highlight

    demo_run(tmp_path)  # fills the cache, including the (stub) highlight
    entry = next((tmp_path / "cache" / "item01").glob("highlight.*.json"))
    gone = Highlight(status="produced", splat_path="runs/item01/gone/splat_highlighted.spz", summary="Marked a scuff.")
    entry.write_text(gone.model_dump_json())  # a cached result whose file is in neither runs/ nor the cache
    result = demo_run(tmp_path)
    assert result.highlight.status == "failed"
    assert "missing" in result.highlight.summary


def fake_highlight_writing_a_file(calls):
    from contracts import Highlight

    async def fake(ctx, splat, views, baseline, identity, cond):
        calls.append(ctx.item_id)
        path = ctx.run_dir / "splat_highlighted.spz"
        path.write_bytes(b"tinted splat")
        return Highlight(status="produced", splat_path=str(path), summary="Marked scratches or scuffs in red.")

    return fake


def test_demo_cache_keeps_the_highlighted_splat(tmp_path, monkeypatch):
    import pipeline

    calls = []
    monkeypatch.setattr(pipeline, "highlight", fake_highlight_writing_a_file(calls))
    demo_run(tmp_path)
    splat = tmp_path / "runs" / "item01" / "splat_highlighted.spz"
    splat.unlink()  # e.g. runs/ was cleaned before the demo
    result = demo_run(tmp_path)
    assert calls == ["item01"]  # the second run came from the cache
    assert result.highlight.status == "produced" and splat.read_bytes() == b"tinted splat"


def test_offline_demo_needs_nothing_live(tmp_path, monkeypatch):
    import pipeline

    demo_run(tmp_path, asking_price_cad=120)
    for name in ("render", "identify", "baseline_lookup", "match_gate", "listing_text", "reference_price",
                 "condition", "highlight"):
        async def must_not_run(*args, name=name):
            raise AssertionError(f"{name} ran in an offline demo")

        monkeypatch.setattr(pipeline, name, must_not_run)
    replay = demo_run(tmp_path, asking_price_cad=120, demo_offline=True)
    assert replay.deal_rating.rating == "great"
    other = demo_run(tmp_path, asking_price_cad=260, demo_offline=True)  # pure code, so a new price still works
    assert other.deal_rating.rating == "overpriced"


def test_offline_demo_reports_a_cold_stage(tmp_path):
    from pipeline import DemoCacheMiss

    with pytest.raises(DemoCacheMiss, match="'render'"):
        demo_run(tmp_path, demo_offline=True)


def test_seller_name_is_part_of_the_cache_key(tmp_path):
    item_dir = tmp_path / "item01"
    shutil.copytree(FIXTURES / "item01", item_dir)
    demo_run(tmp_path, item=item_dir)
    demo_run(tmp_path, item=item_dir, seller_name="Sony WH-1000XM4")
    counts = cached_stages(tmp_path)
    assert counts["render"] == counts["identify"] == 1  # not affected by the seller's name
    assert counts["baseline_lookup"] == counts["reference_price"] == 2


def test_listing_is_written_before_the_highlight_finishes(tmp_path, monkeypatch):
    import pipeline
    from contracts import Highlight

    release = asyncio.Event()
    seen = {}

    async def slow_highlight(ctx, splat, views, baseline, identity, cond):
        await release.wait()
        return Highlight(status="skipped", summary="No highlighted splat: test.")

    def posted(listing):
        seen["status"] = listing.highlight.status
        seen["file"] = json.loads((tmp_path / "runs" / "item01" / "result.json").read_text())["highlight"]["status"]
        release.set()

    monkeypatch.setattr(pipeline, "highlight", slow_highlight)
    result = run(FIXTURES / "item01", tmp_path, on_listing=posted)
    assert seen == {"status": "pending", "file": "pending"}
    assert result.highlight.status == "skipped"
    final = json.loads((tmp_path / "runs" / "item01" / "result.json").read_text())
    assert final["highlight"]["status"] == "skipped" and final["deal_rating"]["rating"] == "fair"


def test_a_quick_highlight_is_in_the_first_write(tmp_path):
    seen = []
    result = run(FIXTURES / "item01", tmp_path, on_listing=lambda listing: seen.append(listing.highlight.status))
    assert seen == ["skipped"] and result.highlight.status == "skipped"  # the stub is ready straight away


def test_rejection_reaches_the_hook(tmp_path):
    seen = []
    result = run(FIXTURES / "item02", tmp_path, on_listing=seen.append)
    assert seen == [result] and type(result).__name__ == "Rejection"


def test_asking_price_from_input_json(tmp_path):
    item_dir = tmp_path / "item_asking"
    shutil.copytree(FIXTURES / "item01", item_dir)
    (item_dir / "input.json").write_text(json.dumps({"seller_name": None, "asking_price_cad": 120}))
    result = run(item_dir, tmp_path)
    assert result.price_cad == 150  # Mint's price doesn't change; the rating judges the asking price against it
    assert result.deal_rating.asking_price_cad == 120 and result.deal_rating.asking_price_source == "seller"
    assert result.deal_rating.rating == "great"


def test_asking_price_argument_wins_over_input_json(tmp_path):
    item_dir = tmp_path / "item_asking"
    shutil.copytree(FIXTURES / "item01", item_dir)
    (item_dir / "input.json").write_text(json.dumps({"seller_name": None, "asking_price_cad": 120}))
    result = run(item_dir, tmp_path, asking_price_cad=260)
    assert result.deal_rating.rating == "overpriced"


@pytest.mark.parametrize("bad", [0, -10, "120", True, float("nan")])
def test_bad_asking_price_fails_early(tmp_path, bad):
    item_dir = tmp_path / "item_bad"
    shutil.copytree(FIXTURES / "item01", item_dir)
    (item_dir / "input.json").write_text(json.dumps({"seller_name": None, "asking_price_cad": bad}))
    with pytest.raises(ValueError, match="asking_price_cad"):
        run(item_dir, tmp_path)
    assert not (tmp_path / "runs" / "item_bad").exists()  # nothing ran


def test_demo_mode_rerates_a_new_asking_price(tmp_path):
    kwargs = dict(runs_root=tmp_path / "runs", cache_root=tmp_path / "cache", demo_mode=True)
    first = asyncio.run(run_pipeline(FIXTURES / "item01", asking_price_cad=120, **kwargs))
    second = asyncio.run(run_pipeline(FIXTURES / "item01", asking_price_cad=260, **kwargs))
    again = asyncio.run(run_pipeline(FIXTURES / "item01", asking_price_cad=120, **kwargs))
    assert [r.deal_rating.rating for r in (first, second, again)] == ["great", "overpriced", "great"]
    counts = cached_stages(tmp_path)
    assert counts["deal_rating"] == 2 and counts["condition"] == 1  # the asking price is part of the key


def test_uncertain_gate_continues_with_seller_check(tmp_path):
    item_dir = tmp_path / "item_uncertain"
    shutil.copytree(FIXTURES / "item01", item_dir)
    views = [{"view_id": f"v{i:02d}", "item_usable": 0.9, "same_category": 0.9, "same_product": 0.45}
             for i in range(12)]  # same_product between mismatch (0.30) and match (0.60)
    (item_dir / "stubs" / "match_gate.json").write_text(json.dumps({"views": views}))
    result = run(item_dir, tmp_path)
    assert isinstance(result, Listing)
    assert result.needs_seller_check is True
    assert len(result.seller_check_reasons) == 1


def test_no_baseline_found_continues_as_uncertain(tmp_path, monkeypatch):
    import stages.baseline_lookup as bl
    from contracts import Baseline

    async def nothing_found(query, run_dir):
        return Baseline(query=query, image_path=None, source="image_search", note="nothing passed"), {}

    monkeypatch.setattr(bl, "find_baseline", nothing_found)
    item_dir = tmp_path / "item_no_baseline"
    shutil.copytree(FIXTURES / "item01", item_dir)
    (item_dir / "stubs" / "baseline_lookup.json").unlink()

    result = run(item_dir, tmp_path)
    assert isinstance(result, Listing)
    assert result.needs_seller_check is True
    assert any("reference photo" in r for r in result.seller_check_reasons)
    gate = json.loads((tmp_path / "runs" / "item_no_baseline" / "match_gate.json").read_text())
    assert gate["verdict"] == "uncertain" and gate["same_product"] is None


def test_generic_identity_skips_search_and_still_prices(tmp_path, monkeypatch):
    """Nothing read off the item and no seller name: no search, uncertain match, condition on views alone, a priced
    Listing."""
    import stages.baseline_lookup as bl
    import stages.condition as cond

    async def must_not_search(query, run_dir):
        raise AssertionError("searched with a generic query")

    asked = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def ask(jev, v, context, questions, baseline_image):
        asked.append(baseline_image)
        return cond.ViewAnswers(v.view_id, nouls={"item_usable": 0.95, "scratches_scuffs": 0.1,
                                                  "stains_discolouration": 0.05, "cracks_tears": 0.02,
                                                  "missing_broken": 0.02},
                                wear_score=1.0, wear_probs={0: 0.1, 1: 0.8, 2: 0.1, 3: 0.0}, wear_confidence=0.8)

    monkeypatch.setattr(bl, "find_baseline", must_not_search)
    monkeypatch.setattr(cond, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(cond, "ask_view", ask)
    monkeypatch.setattr(cond, "_jev_key", lambda: "test-key")

    item_dir = tmp_path / "item_generic"
    shutil.copytree(FIXTURES / "item01", item_dir)
    for stage in ("baseline_lookup", "condition"):
        (item_dir / "stubs" / f"{stage}.json").unlink()
    identity = json.loads((item_dir / "stubs" / "identify.json").read_text())
    identity.update(brand=None, model=None, visible_text=[], search_query="black over-ear headphones")
    (item_dir / "stubs" / "identify.json").write_text(json.dumps(identity))

    result = run(item_dir, tmp_path)
    assert isinstance(result, Listing)
    assert result.price_cad == 150 and result.condition_grade == "light_wear"
    assert result.needs_seller_check is True
    assert len(asked) == 12 and all(b is None for b in asked)


def test_seller_name_reaches_reference_price(tmp_path, monkeypatch):
    import stages.reference_price as rp
    from gemini import GeminiReply
    from stages.identify import GEMINI

    monkeypatch.setitem(GEMINI, "search_grounding", True)  # the grounded answer is the one the test checks

    prompts = []

    async def fake(contents, system_prompt, schema, **kwargs):
        prompts.append(contents)
        return GeminiReply(raw={"amount_cad": 450.0, "note": "Sony WH-1000XM4 at sony.ca."}, model="fake",
                           latency_ms=1.0, grounding=[{"uri": "https://example.test", "title": "sony.ca", "domain": None}])

    monkeypatch.setattr(rp, "generate_json", fake)
    item_dir = tmp_path / "item_seller_named"
    shutil.copytree(FIXTURES / "item01", item_dir)
    (item_dir / "stubs" / "reference_price.json").unlink()
    (item_dir / "input.json").write_text(json.dumps({"seller_name": "Sony WH-1000XM4 Midnight Blue"}))

    result = run(item_dir, tmp_path)
    assert isinstance(result, Listing)
    assert len(prompts) == 1 and "Sony WH-1000XM4 Midnight Blue" in prompts[0]
    assert result.price_cad == 295  # 450 x 0.65 light_wear = 292.50, rounded to the nearest $5
    assert "new price at about $450.00" in result.price_justification[0]


def test_price_sources_reach_result_json(tmp_path, monkeypatch):
    """A price from real listings: the listings are in the Listing (result.json), so the site can show them."""
    import stages.reference_price as rp
    from gemini import GeminiReply

    async def search(query, api_key):
        return {"shopping": [{"title": "Sony WH-1000XM4", "source": "Best Buy Canada", "price": "$449.99",
                              "link": "https://example.test/bb"},
                             {"title": "Sony WH-1000XM4 Wireless", "source": "Amazon CA", "price": "$399.99",
                              "link": "https://example.test/az"}]}

    async def fake(contents, system_prompt, schema, **kwargs):
        return GeminiReply(raw={"results": [{"index": i, "same_product": 0.95, "new_single_unit": True}
                                            for i in range(2)]}, model="fake", latency_ms=1.0)

    monkeypatch.setattr(rp, "search_shopping", search)
    monkeypatch.setattr(rp, "_require_key", lambda name: "test-key")
    monkeypatch.setattr(rp, "generate_json", fake)
    item_dir = tmp_path / "item_listed_price"
    shutil.copytree(FIXTURES / "item01", item_dir)
    (item_dir / "stubs" / "reference_price.json").unlink()

    result = run(item_dir, tmp_path)
    assert isinstance(result, Listing)
    assert result.price_cad == 275  # median $424.99 x 0.65 light_wear = 276.24, rounded to the nearest $5
    saved = json.loads((tmp_path / "runs" / "item_listed_price" / "result.json").read_text(encoding="utf-8"))
    assert [(s["seller"], s["price_cad"]) for s in saved["price_sources"]] == [("Best Buy Canada", 449.99),
                                                                                ("Amazon CA", 399.99)]
    assert result.deal_rating.confidence_notes == []

def test_demo_mode_reads_cache_first(tmp_path):
    ctx = RunContext(item_id="item01", item_dir=FIXTURES / "item01", run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache", demo_mode=True)
    cached = Views.model_validate_json((FIXTURES / "item01" / "stubs" / "render.json").read_text(encoding="utf-8"))
    cache.put(ctx.cache_dir, ctx.item_id, "render", cache.key("render", ctx.up_axis, ctx.manual_baseline, None), cached)

    async def must_not_run(ctx, *args):
        raise AssertionError("stage ran despite a cache hit")

    result = asyncio.run(run_stage(ctx, "render", Views, must_not_run, None))
    assert result == cached
    assert (ctx.run_dir / "render.json").is_file()


def test_demo_mode_fills_cache_on_miss(tmp_path):
    run_pipeline_kwargs = dict(runs_root=tmp_path / "runs", cache_root=tmp_path / "cache", demo_mode=True)
    asyncio.run(run_pipeline(FIXTURES / "item01", **run_pipeline_kwargs))
    assert set(cached_stages(tmp_path)) == {
        "render", "identify", "baseline_lookup", "match_gate", "listing_text", "reference_price", "condition",
        "highlight", "deal_rating", "finalize",
    }


# --- run order: stages start as soon as their inputs exist ------------------------------------------


def slow_render(monkeypatch, seconds=0.15):
    import pipeline

    original = pipeline.render

    async def render(ctx, splat):
        await asyncio.sleep(seconds)
        return await original(ctx, splat)

    monkeypatch.setattr(pipeline, "render", render)


def stage_times(tmp_path, item):
    stages = json.loads((tmp_path / "runs" / item / "timings.json").read_text(encoding="utf-8"))["stages"]
    return {k: (s["start_ms"], s["end_ms"]) for k, s in stages.items()}


def test_with_a_seller_name_the_photo_search_starts_before_the_render_ends(tmp_path, monkeypatch):
    import pipeline

    slow_render(monkeypatch)
    original_gate = pipeline.match_gate

    async def slow_gate(*args):
        await asyncio.sleep(0.05)
        return await original_gate(*args)

    monkeypatch.setattr(pipeline, "match_gate", slow_gate)
    item_dir = tmp_path / "item_named"
    shutil.copytree(FIXTURES / "item01", item_dir)
    (item_dir / "input.json").write_text(json.dumps({"seller_name": "Sony WH-1000XM4"}))
    assert isinstance(run(item_dir, tmp_path), Listing)
    t = stage_times(tmp_path, "item_named")
    assert t["baseline_lookup"][0] < t["render"][1]
    assert t["listing_text"][0] >= t["identify"][1] and t["reference_price"][0] >= t["identify"][1]
    assert t["condition"][0] < t["match_gate"][1]  # beside the match check, not after it


def test_without_a_seller_name_the_photo_search_waits_for_identify(tmp_path, monkeypatch):
    slow_render(monkeypatch)
    run(FIXTURES / "item01", tmp_path)
    t = stage_times(tmp_path, "item01")
    assert t["baseline_lookup"][0] >= t["identify"][1]
    assert t["listing_text"][0] < t["match_gate"][1]  # text and price no longer wait for the match check


def test_a_rejection_stops_the_work_started_beside_the_match_check(tmp_path, monkeypatch):
    import pipeline

    finished = []

    async def slow_text(ctx, identity):
        await asyncio.sleep(2)
        finished.append("listing_text")

    monkeypatch.setattr(pipeline, "listing_text", slow_text)
    result = run(FIXTURES / "item02", tmp_path)
    assert type(result).__name__ == "Rejection" and finished == []
    assert not (tmp_path / "runs" / "item02" / "listing_text.json").exists()
    saved = json.loads((tmp_path / "runs" / "item02" / "result.json").read_text(encoding="utf-8"))
    assert saved["match_check"]["verdict"] == "mismatch"
