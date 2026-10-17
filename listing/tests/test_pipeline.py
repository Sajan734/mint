import asyncio
import json
import shutil
from pathlib import Path

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
    written = {p.stem for p in (tmp_path / "runs" / "item01").glob("*.json")}
    assert written == {
        "render", "identify", "baseline_lookup", "match_gate",
        "listing_text", "reference_price", "condition", "finalize", "result",
    }


def test_item02_gives_rejection(tmp_path):
    result = run(FIXTURES / "item02", tmp_path)
    assert type(result).__name__ == "Rejection"
    assert result.match_check.verdict == "mismatch"
    assert "Sony WH-1000XM4" in result.match_check.reason  # the seller's name from input.json
    assert not (tmp_path / "runs" / "item02" / "finalize.json").exists()


def test_uncertain_gate_continues_with_seller_check(tmp_path):
    item_dir = tmp_path / "item_uncertain"
    shutil.copytree(FIXTURES / "item01", item_dir)
    (item_dir / "stubs" / "match_gate.json").write_text(json.dumps({"same_category": 0.9, "same_product": 0.55}))
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
    """No model and no seller name: no search, uncertain match, condition on views alone, a priced Listing."""
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
    identity.update(model=None, visible_text=["SONY"])
    (item_dir / "stubs" / "identify.json").write_text(json.dumps(identity))

    result = run(item_dir, tmp_path)
    assert isinstance(result, Listing)
    assert result.price_cad == 207 and result.condition_grade == "light_wear"
    assert result.needs_seller_check is True
    assert len(asked) == 12 and all(b is None for b in asked)


def test_demo_mode_reads_cache_first(tmp_path):
    ctx = RunContext(item_id="item01", item_dir=FIXTURES / "item01", run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache", demo_mode=True)
    cached = Views.model_validate_json((FIXTURES / "item01" / "stubs" / "render.json").read_text(encoding="utf-8"))
    cache.put(ctx.cache_dir, ctx.item_id, "render", cached)

    async def must_not_run(ctx, *args):
        raise AssertionError("stage ran despite a cache hit")

    result = asyncio.run(run_stage(ctx, "render", Views, must_not_run, None))
    assert result == cached
    assert (ctx.run_dir / "render.json").is_file()


def test_demo_mode_fills_cache_on_miss(tmp_path):
    run_pipeline_kwargs = dict(runs_root=tmp_path / "runs", cache_root=tmp_path / "cache", demo_mode=True)
    asyncio.run(run_pipeline(FIXTURES / "item01", **run_pipeline_kwargs))
    assert (tmp_path / "cache" / "item01" / "finalize.json").is_file()
