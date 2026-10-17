"""Try identify -> listing_text + reference_price on a folder of photos (real Gemini calls).

    python scripts/try_listing.py path/to/folder [--seller-name "Sony WH-CH510"] [--identity identity.json]

Identifies the item from the folder's images (or loads an Identity JSON with --identity, skipping that call),
then writes the listing text and looks up the reference price concurrently. Prints the draft, the price and
every price attempt. Saves stage outputs and raw logs to runs/try_listing/<folder>/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts import Identity, RunContext  # noqa: E402
from scripts.try_identify import folder_views  # noqa: E402
from stages.identify import MissingKeyError, call_gemini, to_identity  # noqa: E402
from stages.listing_text import listing_text  # noqa: E402
from stages.reference_price import reference_price  # noqa: E402


async def run(args) -> int:
    out_dir = ROOT / "runs" / "try_listing" / args.folder.name
    out_dir.mkdir(parents=True, exist_ok=True)
    # item_dir is the photo folder, which has no stubs/, so every stage runs live.
    ctx = RunContext(item_id=args.folder.name, item_dir=args.folder, run_dir=out_dir, cache_dir=out_dir / "cache")
    try:
        if args.identity:
            identity = Identity.model_validate_json(args.identity.read_text(encoding="utf-8"))
        else:
            views = folder_views(args.folder, args.max_views)
            print(f"{len(views.views)} images from {args.folder}")
            identity, notes = to_identity((await call_gemini(views)).raw)
            for note in notes:
                print(f"evidence rule: {note}")
        (out_dir / "identify.json").write_text(identity.model_dump_json(indent=2), encoding="utf-8")
        print("\nIdentity:")
        print(identity.model_dump_json(indent=2))

        draft, price = await asyncio.gather(
            listing_text(ctx, identity), reference_price(ctx, identity, args.seller_name)
        )
    except MissingKeyError as e:
        print(e, file=sys.stderr)
        return 2
    (out_dir / "listing_text.json").write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "reference_price.json").write_text(price.model_dump_json(indent=2), encoding="utf-8")

    text_log = json.loads((out_dir / "listing_text_raw.json").read_text(encoding="utf-8"))
    price_log = json.loads((out_dir / "reference_price_raw.json").read_text(encoding="utf-8"))
    print(f"\nListingDraft (source: {text_log['source']}, title {len(draft.title)} chars):")
    print(draft.model_dump_json(indent=2))
    for i, attempt in enumerate(text_log["attempts"], 1):
        print(f"  text attempt {i}: {attempt.get('error') or attempt.get('problems') or 'ok'}")
    print(f"\nReferencePrice (source: {price_log['source']}, query {price_log['query']!r}):")
    print(price.model_dump_json(indent=2))
    for attempt in price_log["attempts"]:
        outcome = attempt.get("error") or attempt.get("rejected") or "accepted"
        amount = attempt.get("raw", {}).get("amount_cad")
        print(f"  {attempt['source']}: amount {amount} | {len(attempt.get('grounding', []))} sources | {outcome}")
    print(f"\nsaved to {out_dir.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run identify, listing_text and reference_price on a photo folder.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--seller-name", default=None, help="product name typed by the seller")
    parser.add_argument("--identity", type=Path, default=None, help="Identity JSON to use instead of calling identify")
    parser.add_argument("--max-views", type=int, default=12)
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")  # piped Windows output is cp1252
    if not args.folder.is_dir():
        print(f"Not a folder: {args.folder}", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
