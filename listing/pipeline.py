"""run_pipeline(item_dir, seller_name=None) -> Listing | Rejection.

CLI: python pipeline.py fixtures/item01 [--seller-name "Sony WH-1000XM4"] [--asking-price 120] [--offline]

The item folder holds photos/ (the product from several angles, normally 8 JPGs) and optionally input.json
(seller_name, asking_price_cad, photo_urls: public URLs of the same photos). result.json is written (and on_listing
called) as soon as the listing is ready. DEMO_MODE=1 reads every stage from demo_cache first, keyed by a hash of the
stage's inputs; DEMO_MODE=offline (or --offline) also refuses to call any API, so a demo can't hit a quota.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel

import cache
import timing
from contracts import (
    Baseline,
    Condition,
    DealRating,
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
from stages.identify import identify, warm_gemini
from stages.listing_text import listing_text
from stages.match_gate import match_gate
from stages.load_photos import load_photos, photo_files
from stages.reference_price import reference_price

ROOT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT / "runs"
CACHE_ROOT = ROOT / "demo_cache"

M = TypeVar("M", bound=BaseModel)
ListingHook = Callable[[Listing | Rejection], Awaitable[None] | None]


class DemoCacheMiss(RuntimeError):
    """Offline demo mode, and a stage that calls an API has nothing cached for these inputs."""


def item_input(item_dir: Path) -> dict[str, Any]:
    """The item folder's input.json (seller_name, asking_price_cad, photo_urls), or {} when there is none."""
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
    pure: bool = False,
    files: Callable[[M], list[str | None]] | None = None,
    after: tuple[str, ...] = (),
) -> M:
    """Runs one stage and writes its JSON. In demo mode every stage reads the cache first, keyed by a hash of its
    inputs and the run settings, so a new asking price or seller name is a miss, never a stale hit; misses are
    cached, with the files `files` names. Offline, a miss raises DemoCacheMiss unless the stage is pure code.
    after: the stages it waited for, so timings.json can trace the critical path."""
    with timing.stage(name, after) as timed:
        result, hit = await _run_stage(ctx, name, model, fn, *args, pure=pure, files=files)
        if timed is not None:
            timed.cache_hit = hit
    return result


async def _run_stage(ctx: RunContext, name: str, model: type[M], fn: Callable[..., Awaitable[M]], *args: Any,
                     pure: bool, files: Callable[[M], list[str | None]] | None) -> tuple[M, bool]:
    start = time.perf_counter()
    key = cache.key(name, ctx.manual_baseline, *args) if ctx.demo_mode else ""
    result = cache.get(ctx.cache_dir, ctx.item_id, name, key, model) if ctx.demo_mode else None
    hit = result is not None
    if result is None:
        if ctx.demo_offline and not pure:
            raise DemoCacheMiss(
                f"the demo cache has no {name!r} for item {ctx.item_id!r} with these inputs; "
                "run it once with DEMO_MODE=1 (online) first"
            )
        result = await fn(ctx, *args)
        if ctx.demo_mode:
            cache.put(ctx.cache_dir, ctx.item_id, name, key, result, files(result) if files else [])
    write_json(ctx.run_dir / f"{name}.json", result)
    ms = (time.perf_counter() - start) * 1000
    print(f"[{name}] {ms:.0f} ms{' (cache)' if hit else ''}", file=sys.stderr)
    return result, hit


def write_timings(ctx: RunContext, ends: dict[str, str]) -> None:
    """runs/<item>/timings.json: every stage's wall, external and own time, the milestones, and the critical path to
    each milestone (ends: milestone -> the stage that completed it)."""
    run = timing.current_run()
    if run is not None:
        timing.write(run, ctx.run_dir / "timings.json", ends, {"item_id": ctx.item_id, "demo_mode": ctx.demo_mode})


def write_result(ctx: RunContext, result: Listing | Rejection, milestone: str, ends: dict[str, str]) -> None:
    write_json(ctx.run_dir / "result.json", result)
    timing.milestone(milestone)
    write_timings(ctx, ends)


def photos_key(item_dir: Path) -> list[list]:
    """The photos' names and sizes: part of load_photos' demo-cache key, so changed photos are a miss."""
    try:
        return [[p.name, p.stat().st_size] for p in photo_files(item_dir)]
    except ValueError:
        return []


async def notify(on_listing: ListingHook | None, result: Listing | Rejection) -> None:
    if on_listing is not None:
        outcome = on_listing(result)
        if inspect.isawaitable(outcome):
            await outcome


async def run_pipeline(
    item_path: Path | str,
    seller_name: str | None = None,
    *,
    runs_root: Path | None = None,
    cache_root: Path | None = None,
    demo_mode: bool | None = None,
    manual_baseline: bool | None = None,
    asking_price_cad: float | None = None,
    demo_offline: bool | None = None,
    on_listing: ListingHook | None = None,
) -> Listing | Rejection:
    """Returns the finished result; on_listing gets it too, the moment result.json is written (e.g. to post it)."""
    item_dir = Path(item_path)
    item_id = item_dir.name
    inputs = item_input(item_dir)
    if seller_name is None:
        seller_name = inputs.get("seller_name")
    asking = asking_price(asking_price_cad if asking_price_cad is not None else inputs.get("asking_price_cad"))
    demo_env = os.environ.get("DEMO_MODE", "").strip().lower()
    offline = demo_env == "offline" if demo_offline is None else demo_offline
    ctx = RunContext(
        item_id=item_id,
        item_dir=item_dir,
        run_dir=(runs_root or RUNS_ROOT) / item_id,
        cache_dir=cache_root or CACHE_ROOT,
        demo_mode=offline or (demo_env in ("1", "offline") if demo_mode is None else demo_mode),
        demo_offline=offline,
        manual_baseline=(
            os.environ.get("MANUAL_BASELINE") == "1" if manual_baseline is None else manual_baseline
        ),
    )

    timing.start_run()
    pending: list[asyncio.Task] = []

    def start(coro: Awaitable[M]) -> asyncio.Task[M]:
        task = asyncio.ensure_future(coro)
        pending.append(task)
        return task

    # Everything starts as soon as its inputs exist. Gemini's client is set up while the photos load.
    # With a seller-typed name the reference photo search needs nothing from the photos, so it starts right away.
    start(warm_gemini())
    seller_named = bool(seller_name and seller_name.strip())
    baseline_task = start(run_stage(ctx, "baseline_lookup", Baseline, baseline_lookup, None, seller_name)) \
        if seller_named else None
    try:
        views = await run_stage(ctx, "load_photos", Views, load_photos, inputs.get("photo_urls"),
                                photos_key(item_dir))
        identity = await run_stage(ctx, "identify", Identity, identify, views, seller_name, after=("load_photos",))
        # These only need the identity: they run alongside the match check and are dropped if it rejects the item.
        text_task = start(run_stage(ctx, "listing_text", ListingDraft, listing_text, identity, after=("identify",)))
        price_task = start(run_stage(ctx, "reference_price", ReferencePrice, reference_price, identity, seller_name,
                                     after=("identify",)))
        if baseline_task is None:
            baseline_task = start(run_stage(ctx, "baseline_lookup", Baseline, baseline_lookup, identity, seller_name,
                                            after=("identify",)))
        baseline = await baseline_task
        match_task = start(run_stage(ctx, "match_gate", MatchCheck, match_gate, views, baseline, identity,
                                     seller_name, after=("baseline_lookup", "identify")))
        # condition compares the same photos with the same reference; it runs beside the match check (its Jev
        # requests are wasted only when the item is rejected).
        cond_task = start(run_stage(ctx, "condition", Condition, condition, views, baseline, identity,
                                    after=("baseline_lookup", "identify")))
        match = await match_task

        if match.verdict == "mismatch":
            rejection = Rejection(item_id=item_id, match_check=match)
            write_result(ctx, rejection, "result_json", {"result_json": "match_gate"})
            await notify(on_listing, rejection)
            return rejection

        cond = await cond_task
        draft, reference = await asyncio.gather(text_task, price_task)
        deal = await run_stage(
            ctx, "deal_rating", DealRating, deal_rating, reference, cond, match, baseline, asking, pure=True,
            after=("reference_price", "condition", "match_gate"),
        )
        result = await run_stage(
            ctx, "finalize", Listing, finalize, views, match, baseline, draft, reference, cond, deal, pure=True,
            after=("deal_rating", "listing_text"),
        )
        write_result(ctx, result, "result_json", {"result_json": "finalize"})
        await notify(on_listing, result)
    finally:
        # A rejection, an error or an offline cache miss leaves work running: stop it, and let it finish unwinding.
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn an item's photos into a Listing or a Rejection.")
    parser.add_argument("item", type=Path, help="item folder with photos/ (e.g. fixtures/item01)")
    parser.add_argument("--seller-name", default=None, help="product name typed by the seller")
    parser.add_argument(
        "--manual-baseline",
        action="store_true",
        default=None,
        help="use the item folder's baseline.jpg/png and never search (also MANUAL_BASELINE=1)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        default=None,
        help="demo mode that never calls an API: fails on a stage the demo cache doesn't have (also DEMO_MODE=offline)",
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
        run_pipeline(args.item, args.seller_name, manual_baseline=args.manual_baseline,
                     asking_price_cad=args.asking_price, demo_offline=args.offline)
    )
    print(f"{type(result).__name__}:", file=sys.stderr)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
