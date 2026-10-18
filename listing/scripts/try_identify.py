"""Try the identify stage alone on an item folder (live: Gemini read + Lens + fuse).

    python scripts/try_identify.py samples/<scan_id> [--seller-name "Logitech MX Master 3S"]

The folder needs photos/ (and optionally input.json with photo_urls, else 2 photos are uploaded for Lens). Prints the
Identity, what backed it, what wasn't claimed and why, and the Lens titles. Output: runs/try_identify/<item>/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts import RunContext  # noqa: E402
from pipeline import item_input  # noqa: E402
from stages.identify import MissingKeyError, identify  # noqa: E402
from stages.load_photos import load_views  # noqa: E402


async def run(args) -> int:
    out_dir = ROOT / "runs" / "try_identify" / args.item.name
    inputs = item_input(args.item)
    seller = args.seller_name if args.seller_name is not None else inputs.get("seller_name")
    views = load_views(args.item, args.item.name, out_dir / "views", inputs.get("photo_urls"))
    ctx = RunContext(item_id=args.item.name, item_dir=args.item, run_dir=out_dir, cache_dir=out_dir / "cache")
    try:
        identity = await identify(ctx, views, seller)
    except MissingKeyError as e:
        print(e, file=sys.stderr)
        return 2
    log = json.loads((out_dir / "identify_raw.json").read_text(encoding="utf-8"))
    print(identity.model_dump_json(indent=2))
    print("\nnot claimed:", *log["decision_notes"] or ["-"], sep="\n  ")
    print("\nfuse:", json.dumps(log["fuse"].get("raw") or log["fuse"], ensure_ascii=False))
    print("\nLens titles:", *[m["title"] for m in log["lens"].get("matches", [])[:15]] or ["-"], sep="\n  ")
    print(f"\nsaved to {out_dir.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("item", type=Path, help="item folder with photos/")
    parser.add_argument("--seller-name", default=None)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
