"""run_pipeline(splat_path, seller_name=None) -> Listing | Rejection.

CLI: python pipeline.py fixtures/item01 [--seller-name "Sony WH-1000XM4"] [--asking-price 120]
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
    DealRating,
    Highlight,
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
from stages.deal_rating import asking_price, deal_rating
from stages.finalize import finalize
from stages.highlight import highlight, not_produced
from stages.identify import identify
from stages.listing_text import listing_text
from stages.match_gate import match_gate
from stages.reference_price import reference_price
from stages.render import render

ROOT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT / "runs"
CACHE_ROOT = ROOT / "demo_cache"
SPLAT_NAMES = ("splat.spz", "splat.ply")  # an item folder's splat: the published .spz, else a .ply

M = TypeVar("M", bound=BaseModel)


def resolve_item(path: Path) -> tuple[Path, Path]:
    """Returns (item_dir, splat_path) for an item folder or a splat file."""
    path = Path(path)
    if path.suffix:
        return path.parent, path
    return path, next((path / n for n in SPLAT_NAMES if (path / n).is_file()), path / SPLAT_NAMES[-1])


def item_input(item_dir: Path) -> dict[str, Any]:
    """The item folder's input.json (seller_name, up_axis, asking_price_cad), or {} when there is none."""
    path = item_dir / "input.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")


async def run_stage(
    ctx: RunContext,
    name: str,
    model: type[M],
    fn: Callable[..., Awaitable[M]],
    *args: Any,
    cached: bool = True,
) -> M:
    """Runs one stage and writes its JSON. In demo mode, stages that call an API or a GPU read the cache first;
    pure-code stages (cached=False) always recompute from their inputs, so e.g. a new asking price takes effect."""
    start = time.perf_counter()
    use_cache = ctx.demo_mode and cached
    result = cache.get(ctx.cache_dir, ctx.item_id, name, model) if use_cache else None
    hit = result is not None
    if result is None:
        result = await fn(ctx, *args)
        if use_cache:
            cache.put(ctx.cache_dir, ctx.item_id, name, result)
    write_json(ctx.run_dir / f"{name}.json", result)
    ms = (time.perf_counter() - start) * 1000
    print(f"[{name}] {ms:.0f} ms{' (cache)' if hit else ''}", file=sys.stderr)
    return result


def listing_path(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


async def run_highlight(ctx: RunContext, splat: Path, views: Views, baseline: Baseline, cond: Condition) -> Highlight:
    """The highlighted splat is a nice-to-have: any error becomes produced=False and the listing goes on.
    Errors aren't cached, so the next run tries again."""
    try:
        result = await run_stage(ctx, "highlight", Highlight, highlight, splat, views, baseline, cond)
    except Exception as e:  # noqa: BLE001  see docstring
        print(f"[highlight] failed, the listing goes on: {type(e).__name__}: {e}", file=sys.stderr)
        result = not_produced(f"the highlight step failed ({type(e).__name__}: {e})")
        write_json(ctx.run_dir / "highlight.json", result)
        return result
    if result.produced and not listing_path(result.splat_path).is_file():  # a cache hit whose file was deleted
        result = not_produced("the cached highlighted splat file is missing; rerun without DEMO_MODE")
        write_json(ctx.run_dir / "highlight.json", result)
    return result


async def run_pipeline(
    splat_path: Path | str,
    seller_name: str | None = None,
    *,
    runs_root: Path | None = None,
    cache_root: Path | None = None,
    demo_mode: bool | None = None,
    manual_baseline: bool | None = None,
    up_axis: str | None = None,
    asking_price_cad: float | None = None,
) -> Listing | Rejection:
    item_dir, splat = resolve_item(Path(splat_path))
    item_id = item_dir.name
    inputs = item_input(item_dir)
    if seller_name is None:
        seller_name = inputs.get("seller_name")
    asking = asking_price(asking_price_cad if asking_price_cad is not None else inputs.get("asking_price_cad"))
    ctx = RunContext(
        item_id=item_id,
        item_dir=item_dir,
        run_dir=(runs_root or RUNS_ROOT) / item_id,
        cache_dir=cache_root or CACHE_ROOT,
        demo_mode=os.environ.get("DEMO_MODE") == "1" if demo_mode is None else demo_mode,
        manual_baseline=(
            os.environ.get("MANUAL_BASELINE") == "1" if manual_baseline is None else manual_baseline
        ),
        up_axis=up_axis or inputs.get("up_axis", "+y"),
    )

    views = await run_stage(ctx, "render", Views, render, splat)
    identity = await run_stage(ctx, "identify", Identity, identify, views)
    baseline = await run_stage(ctx, "baseline_lookup", Baseline, baseline_lookup, identity, seller_name)
    match = await run_stage(ctx, "match_gate", MatchCheck, match_gate, views, baseline)

    result: Listing | Rejection
    if match.verdict == "mismatch":
        result = Rejection(item_id=item_id, match_check=match)
    else:

        async def condition_then_highlight() -> tuple[Condition, Highlight]:
            cond = await run_stage(ctx, "condition", Condition, condition, views, baseline)
            return cond, await run_highlight(ctx, splat, views, baseline, cond)

        draft, reference, (cond, marked) = await asyncio.gather(
            run_stage(ctx, "listing_text", ListingDraft, listing_text, identity),
            run_stage(ctx, "reference_price", ReferencePrice, reference_price, identity, seller_name),
            condition_then_highlight(),
        )
        deal = await run_stage(
            ctx, "deal_rating", DealRating, deal_rating, reference, cond, match, baseline, asking, cached=False
        )
        result = await run_stage(
            ctx, "finalize", Listing, finalize, views, match, baseline, draft, reference, cond, deal, marked,
            cached=False,
        )

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
    parser.add_argument(
        "--up-axis",
        choices=["+x", "-x", "+y", "-y", "+z", "-z"],
        default=None,
        help="splat axis pointing up (default: input.json's up_axis, else +y)",
    )
    parser.add_argument(
        "--asking-price",
        type=float,
        default=None,
        help="seller's asking price in CAD for the deal rating (default: input.json's asking_price_cad, "
        "else Mint's suggested price is rated)",
    )
    args = parser.parse_args(argv)
    try:
        asking_price(args.asking_price)
    except ValueError as e:
        parser.error(str(e))

    result = asyncio.run(
        run_pipeline(args.item, args.seller_name, manual_baseline=args.manual_baseline, up_axis=args.up_axis,
                     asking_price_cad=args.asking_price)
    )
    print(f"{type(result).__name__}:", file=sys.stderr)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
