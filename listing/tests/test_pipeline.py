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
