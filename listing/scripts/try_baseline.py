"""Try baseline lookup live (Serper image search + Jev photo check).

    python scripts/try_baseline.py "Sony WH-CH510 blue"

Prints every candidate with its Jev answers and why it passed or failed, then the chosen photo.
Saves the photo and the candidate log under runs/try_baseline/<slug>/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stages.baseline_lookup import GOOD_IF_NO, GOOD_IF_YES, find_baseline  # noqa: E402
from stages.identify import MissingKeyError  # noqa: E402

SHORT = {
    "single_product": "single",
    "plain_background": "plain",
    "matches_query": "match",
    "people_or_packaging": "ppl/pkg",
    "overlay_or_collage": "overlay",
}


def show_candidate(c: dict) -> str:
    head = f"  #{c['position']:<2} {str(c.get('domain') or '?')[:28]:<28} {c.get('width')}x{c.get('height')}"
    if "answers" in c:
        a = c["answers"]
        scores = " ".join(f"{SHORT[q]} {a[q]:.2f}" for q in (*GOOD_IF_YES, *GOOD_IF_NO))
        verdict = "PASS" if not c["failed"] else "fail: " + ", ".join(SHORT[q] for q in c["failed"])
        return f"{head}  {scores}  weakest {c['weakest']:.2f}  {verdict}"
    return f"{head}  skipped: {c.get('problem')}"


async def run(query: str) -> int:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:60] or "query"
    out_dir = ROOT / "runs" / "try_baseline" / slug
    try:
        baseline, log = await find_baseline(query, out_dir)
    except MissingKeyError as e:
        print(e, file=sys.stderr)
        return 2
    for attempt in log["attempts"]:
        print(f"\nsearch: {attempt['query_sent']!r}")
        if "error" in attempt:
            print(f"  {attempt['error']}")
            continue
        print(f"  {attempt['results']} results")
        for c in attempt["candidates"]:
            print(show_candidate(c))
    print("\nBaseline:")
    print(baseline.model_dump_json(indent=2))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"\nsaved {(out_dir / 'candidates.json').relative_to(ROOT)}")
    return 0 if baseline.image_path else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the live baseline lookup for a query.")
    parser.add_argument("query", help="product name, e.g. the seller's typed name or Identity.search_query")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")  # piped Windows output is cp1252
    return asyncio.run(run(args.query))


if __name__ == "__main__":
    sys.exit(main())
