"""run_pipeline(splat_path, seller_name=None) -> Listing | Rejection.

CLI: python pipeline.py fixtures/item01 [--seller-name "Sony WH-1000XM4"]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel

import cache
from contracts import (
    Baseline,
    Condition,
    Identity,
    Listing,
    ListingDraft,
    MatchCheck,
    ReferencePrice,
    Rejection,
    RunContext,
    Views,
)
from stages.baseline_lookup import baseline_lookup
from stages.condition import condition
from stages.finalize import finalize
from stages.identify import identify
from stages.listing_text import listing_text
from stages.match_gate import match_gate
from stages.reference_price import reference_price
from stages.render import render

ROOT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT / "runs"
CACHE_ROOT = ROOT / "demo_cache"
SPLAT_NAME = "splat.ply"

M = TypeVar("M", bound=BaseModel)


def resolve_item(path: Path) -> tuple[Path, Path]:
    """Returns (item_dir, splat_path) for an item folder or a splat file."""
    path = Path(path)
    if path.suffix:
        return path.parent, path
    return path, path / SPLAT_NAME


def fixture_seller_name(item_dir: Path) -> str | None:
    path = item_dir / "input.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("seller_name")


def write_json(path: Path, obj: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")


async def run_stage(
    ctx: RunContext,
    name: str,
    model: type[M],
    fn: Callable[..., Awaitable[M]],
    *args: Any,
) -> M:
    start = time.perf_counter()
    result = cache.get(ctx.cache_dir, ctx.item_id, name, model) if ctx.demo_mode else None
    hit = result is not None
    if result is None:
        result = await fn(ctx, *args)
        if ctx.demo_mode:
            cache.put(ctx.cache_dir, ctx.item_id, name, result)
    write_json(ctx.run_dir / f"{name}.json", result)
    ms = (time.perf_counter() - start) * 1000
    print(f"[{name}] {ms:.0f} ms{' (cache)' if hit else ''}", file=sys.stderr)
    return result


async def run_pipeline(
    splat_path: Path | str,
    seller_name: str | None = None,
    *,
    runs_root: Path | None = None,
    cache_root: Path | None = None,
    demo_mode: bool | None = None,
    manual_baseline: bool | None = None,
) -> Listing | Rejection:
    item_dir, splat = resolve_item(Path(splat_path))
    item_id = item_dir.name
    if seller_name is None:
        seller_name = fixture_seller_name(item_dir)
    ctx = RunContext(
        item_id=item_id,
        item_dir=item_dir,
        run_dir=(runs_root or RUNS_ROOT) / item_id,
        cache_dir=cache_root or CACHE_ROOT,
        demo_mode=os.environ.get("DEMO_MODE") == "1" if demo_mode is None else demo_mode,
        manual_baseline=(
            os.environ.get("MANUAL_BASELINE") == "1" if manual_baseline is None else manual_baseline
        ),
    )

    views = await run_stage(ctx, "render", Views, render, splat)
    identity = await run_stage(ctx, "identify", Identity, identify, views)
    baseline = await run_stage(ctx, "baseline_lookup", Baseline, baseline_lookup, identity, seller_name)
    match = await run_stage(ctx, "match_gate", MatchCheck, match_gate, views, baseline)

    result: Listing | Rejection
    if match.verdict == "mismatch":
        result = Rejection(item_id=item_id, match_check=match)
    else:
        draft, reference, cond = await asyncio.gather(
            run_stage(ctx, "listing_text", ListingDraft, listing_text, identity),
            run_stage(ctx, "reference_price", ReferencePrice, reference_price, identity),
            run_stage(ctx, "condition", Condition, condition, views, baseline),
        )
        result = await run_stage(ctx, "finalize", Listing, finalize, views, match, draft, reference, cond)

    write_json(ctx.run_dir / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn a trained splat into a Listing or a Rejection.")
    parser.add_argument("item", type=Path, help="item folder (e.g. fixtures/item01) or a splat file")
    parser.add_argument("--seller-name", default=None, help="product name typed by the seller")
    parser.add_argument(
        "--manual-baseline",
        action="store_true",
        default=None,
        help="use the item folder's baseline.jpg/png and never search (also MANUAL_BASELINE=1)",
    )
    args = parser.parse_args(argv)

    result = asyncio.run(run_pipeline(args.item, args.seller_name, manual_baseline=args.manual_baseline))
    print(f"{type(result).__name__}:", file=sys.stderr)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
