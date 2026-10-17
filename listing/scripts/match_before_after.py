"""The match check and new price before and after, on every listing in Supabase. Reads Supabase only.

    python scripts/match_before_after.py [scan_id ...] [--skip-ingest]

Before: what Supabase recorded (the public listings/index.json and each scan's listings/<id>/run/ files).
After: this checkout on the same splat, with the seller's name the scan was listed with: ingest.py downloads it
to samples/<scan_id>/, then render -> identify -> baseline_lookup -> match_gate -> reference_price run live
(stage JSON in runs/<scan_id>/). Writes runs/match_before_after.json and prints one row per scan.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts import Baseline, Identity, MatchCheck, ReferencePrice, RunContext, Views  # noqa: E402
from ingest import IngestError, fetch, ingest, public_url  # noqa: E402
from pipeline import CACHE_ROOT, RUNS_ROOT, item_input, resolve_item, run_stage  # noqa: E402
from stages.baseline_lookup import baseline_lookup  # noqa: E402
from stages.identify import identify  # noqa: E402
from stages.match_gate import match_gate  # noqa: E402
from stages.reference_price import reference_price  # noqa: E402
from stages.render import render  # noqa: E402

SAMPLES = ROOT / "samples"
QUERY_IN_REASON = re.compile(r"reference photo for (.+?), so we couldn't")
PRICE_IN_JUSTIFICATION = re.compile(r"new price is about \$([\d,]+\.\d\d)")


def run_file(scan_id: str, name: str) -> dict[str, Any] | None:
    try:
        return json.loads(fetch(public_url(f"listings/{scan_id}/run/{name}.json")))
    except IngestError:
        return None


def before(doc: dict[str, Any]) -> dict[str, Any]:
    """What Supabase recorded for one scan. Older listings have no run/ files: the match and query are read from
    the seller-facing reason, the price from the justification."""
    scan_id = doc["scan_id"]
    listing = (doc.get("market_listing") or {}).get("listing") or {}
    match = run_file(scan_id, "match_gate") if doc.get("run_files") else None
    if match is None and doc.get("status") == "rejected":
        match = doc["rejection"]["match_check"]
    reasons = listing.get("seller_check_reasons") or []
    query = (run_file(scan_id, "baseline_lookup") or {}).get("query") if doc.get("run_files") else None
    if match is None:
        no_photo = next((r for r in reasons if "couldn't find a reference photo" in r), None)
        match = {"verdict": "uncertain" if no_photo else "match", "same_product": None, "reason": no_photo or ""}
        if no_photo and (m := QUERY_IN_REASON.search(no_photo)):
            query = m.group(1)
    price = run_file(scan_id, "reference_price") if doc.get("run_files") else None
    if price is None:
        m = PRICE_IN_JUSTIFICATION.search(" ".join(listing.get("price_justification") or []))
        price = {"amount_cad": float(m.group(1).replace(",", "")) if m else None, "basis": "llm_estimate", "sources": []}
    return {"status": doc.get("status"), "seller_name": doc.get("seller_name"), "query": query,
            "verdict": match["verdict"], "same_product": match.get("same_product"), "reason": match.get("reason"),
            "price": price.get("amount_cad"), "price_basis": price.get("basis"), "title": listing.get("title")}


async def after(scan_id: str, seller_name: str | None) -> dict[str, Any]:
    item_dir, splat = resolve_item(SAMPLES / scan_id)
    ctx = RunContext(item_id=scan_id, item_dir=item_dir, run_dir=RUNS_ROOT / scan_id, cache_dir=CACHE_ROOT,
                     up_axis=item_input(item_dir).get("up_axis", "+y"))
    views = await run_stage(ctx, "render", Views, render, splat)
    identity = await run_stage(ctx, "identify", Identity, identify, views)
    baseline = await run_stage(ctx, "baseline_lookup", Baseline, baseline_lookup, identity, seller_name)
    match = await run_stage(ctx, "match_gate", MatchCheck, match_gate, views, baseline, identity, seller_name)
    price = await run_stage(ctx, "reference_price", ReferencePrice, reference_price, identity, seller_name)
    return {"query": baseline.query, "baseline_url": baseline.source_url, "baseline_note": baseline.note,
            "verdict": match.verdict, "same_category": match.same_category, "same_product": match.same_product,
            "reason": match.reason, "price": price.amount_cad, "price_basis": price.basis,
            "price_sources": [s.model_dump() for s in price.sources]}


def fmt(row: dict[str, Any]) -> str:
    b, a = row["before"], row.get("after") or {}
    score = lambda x: "  -  " if x is None else f"{x:.2f}"  # noqa: E731
    price = lambda x, basis: "   -   " if x is None else f"${x:>6.2f} {basis}"  # noqa: E731
    lines = [f"{row['scan_id'][:8]}  seller name: {b['seller_name'] or '-'}",
             f"   before: {b['verdict']:<9} product {score(b['same_product'])}  query {b['query']!r}  "
             f"price {price(b['price'], b['price_basis'])}"]
    if "error" in row:
        lines.append(f"   after:  ERROR {row['error']}")
    elif a:
        lines.append(f"   after:  {a['verdict']:<9} product {score(a['same_product'])}  query {a['query']!r}  "
                     f"price {price(a['price'], a['price_basis'])}")
        lines.append(f"           baseline {a['baseline_url'] or a['baseline_note']}")
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    docs = json.loads(fetch(public_url("listings/index.json"), fresh=True))["scans"]
    if args.scan_ids:
        docs = [d for d in docs if any(d["scan_id"].startswith(s) for s in args.scan_ids)]
    rows = []
    for doc in docs:
        scan_id = doc["scan_id"]
        row: dict[str, Any] = {"scan_id": scan_id, "before": before(doc)}
        seller_name = doc.get("seller_name")
        try:
            if not (args.skip_ingest and (SAMPLES / scan_id / "splat.spz").is_file()):
                ingest(scan_id, seller_name)
            row["after"] = await after(scan_id, seller_name)
        except Exception as e:  # noqa: BLE001  one scan failing shouldn't stop the table
            row["error"] = f"{type(e).__name__}: {e}"
        print(fmt(row), flush=True)
        rows.append(row)
    out = RUNS_ROOT / "match_before_after.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT).as_posix()}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Match check and price, before (Supabase) and after (this code).")
    parser.add_argument("scan_ids", nargs="*", help="only these scans (id prefixes); default: every listing")
    parser.add_argument("--skip-ingest", action="store_true", help="reuse samples/<scan_id> when it's there")
    return asyncio.run(main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
