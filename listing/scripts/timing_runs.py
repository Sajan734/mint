"""Run the pipeline on one item a few times and keep each run's timings.json, for before/after comparisons.

    python scripts/timing_runs.py samples/<scan_id> --label before --runs 2
    python scripts/timing_runs.py --summary runs/timing/<scan_id>

Each run is a real, live run (DEMO_MODE off): it spends Gemini, Serper and Jev requests, so keep --runs small.
Saves runs/timing/<item>/<label>-<n>.json (timings.json plus the run's outcome) and prints one line per run.
--summary prints a table of every saved run of an item.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "runs" / "timing"
KINDS = ("gemini", "jev", "serper", "download", "own")


def line(name: str, data: dict) -> str:
    m = data.get("milestones_ms", {})
    breakdown = data.get("critical_path_breakdown_ms", {}).get("result_json", {})
    path = " > ".join(p["stage"] for p in data.get("critical_path", {}).get("result_json", []))
    parts = " ".join(f"{k} {breakdown[k] / 1000:.1f}" for k in KINDS if breakdown.get(k))
    return f"{name:<22} result.json {m.get('result_json', 0) / 1000:5.1f} s  | path: {path} | {parts}"


async def one(item: Path, label: str, n: int) -> None:
    os.environ.pop("DEMO_MODE", None)
    from pipeline import RUNS_ROOT, run_pipeline

    item_dir = Path(item)
    start = time.perf_counter()
    result = await run_pipeline(item, demo_mode=False, demo_offline=False)
    total = time.perf_counter() - start
    data = json.loads((RUNS_ROOT / item_dir.name / "timings.json").read_text(encoding="utf-8"))
    data["outcome"] = {"kind": type(result).__name__, "total_s": round(total, 2)}
    if type(result).__name__ == "Listing":
        data["outcome"] |= {"title": result.title, "price_cad": result.price_cad, "notes": result.condition_notes}
    out = OUT / item_dir.name / f"{label}-{n}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(line(f"{label}-{n}", data), flush=True)


def summary(folder: Path) -> None:
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime):
        print(line(path.stem, json.loads(path.read_text(encoding="utf-8"))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Timed live runs of the listing pipeline.")
    parser.add_argument("item", type=Path, nargs="?", help="item folder, e.g. samples/<scan_id>")
    parser.add_argument("--label", default="run")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--summary", type=Path, help="print the saved runs in this folder instead")
    args = parser.parse_args(argv)
    if args.summary:
        summary(args.summary)
        return 0
    if args.item is None:
        parser.error("give an item folder, or --summary")
    for n in range(1, args.runs + 1):
        asyncio.run(one(args.item, args.label, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
