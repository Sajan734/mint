"""Run the real condition stage live on photo sets and show the numbers side by side.

    python scripts/try_condition.py scripts/smoke --repeat 3 [--baseline path/to/new_product.jpg]

Each argument is a folder. If it has subfolders with images (e.g. smoke/clean, smoke/worn), each subfolder
is one item and its images are that item's views. Otherwise each image is its own one-view item.
Every set runs --repeat times so run-to-run noise is visible. Raw answers go to runs/try_condition/.
Note: sets with fewer than 6 usable views are always flagged "only N views were usable" (the stage's rule).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts import View, Views  # noqa: E402
from stages.condition import DEFECT_KINDS, aggregates, ask_views, build_condition, usable_pool  # noqa: E402
from stages.identify import MissingKeyError  # noqa: E402

SUFFIXES = {".png", ".jpg", ".jpeg"}
SHORT = {"scratches_scuffs": "scratch/scuff", "stains_discolouration": "stain", "cracks_tears": "crack/tear",
         "missing_broken": "missing/broken"}


def images_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)


def photo_sets(paths: list[Path]) -> dict[str, list[Path]]:
    sets: dict[str, list[Path]] = {}
    for path in paths:
        subfolders = [d for d in sorted(path.iterdir()) if d.is_dir() and images_in(d)]
        if subfolders:
            sets |= {d.name: images_in(d) for d in subfolders}
        else:
            sets |= {p.stem: [p] for p in images_in(path)}
    return sets


def as_views(name: str, images: list[Path]) -> Views:
    return Views(item_id=name, views=[
        View(view_id=f"v{i:02d}", label=p.name, azimuth_deg=0, elevation_deg=0, image_path=str(p.resolve()))
        for i, p in enumerate(images)
    ])


async def run_set(name: str, images: list[Path], baseline: str | None, repeat: int) -> list[dict]:
    runs = []
    for _ in range(repeat):
        answers = await ask_views(as_views(name, images), baseline)
        condition, reasons = build_condition(answers)
        usable, pool = usable_pool(answers)
        runs.append({
            "condition": condition, "reasons": reasons, "aggregates": aggregates(pool),
            "usable": len(usable), "views": len(answers),
            "errors": [a.error for a in answers if a.error], "answers": [asdict(a) for a in answers],
        })
    return runs


def table(results: dict[str, list[dict]]) -> str:
    cols = [(name, i, run) for name, runs in results.items() for i, run in enumerate(runs, 1)]
    rows = [
        ("grade", lambda r: r["condition"].grade),
        ("wear (0-3, 2nd-high)", lambda r: f"{r['aggregates']['wear']:.2f}"),
        ("grade support", lambda r: f"{r['condition'].grade_score:.2f}"),
        ("grade confidence", lambda r: f"{r['condition'].grade_confidence:.2f}"),
        *[(SHORT[q], lambda r, q=q: f"{r['aggregates'][q]:.2f}") for q in DEFECT_KINDS],
        ("defects reported", lambda r: ",".join(d.kind for d in r["condition"].defects) or "-"),
        ("usable views", lambda r: f"{r['usable']}/{r['views']}"),
        ("seller check", lambda r: "yes" if r["condition"].needs_seller_check else "no"),
    ]
    width = max(14, *(len(f"{n} #{i}") + 2 for n, i, _ in cols))
    lines = [f"{'':<22}" + "".join(f"{f'{n} #{i}':>{width}}" for n, i, _ in cols)]
    lines += [f"{label:<22}" + "".join(f"{fn(r):>{width}}" for _, _, r in cols) for label, fn in rows]
    return "\n".join(lines)


async def run(args) -> int:
    sets = photo_sets(args.paths)
    if not sets:
        print("No PNG or JPEG photos found in " + ", ".join(map(str, args.paths)), file=sys.stderr)
        return 1
    print(f"{len(sets)} set(s): " + ", ".join(f"{n} ({len(imgs)} photo{'s' * (len(imgs) != 1)})" for n, imgs in sets.items()))
    print(f"baseline: {args.baseline or 'none (view-only questions)'} | repeat {args.repeat}\n")
    try:
        results = {name: await run_set(name, imgs, args.baseline, args.repeat) for name, imgs in sets.items()}
    except MissingKeyError as e:
        print(e, file=sys.stderr)
        return 2
    print(table(results))
    for name, runs in results.items():
        for i, r in enumerate(runs, 1):
            for note in r["errors"] + r["reasons"]:
                print(f"  {name} #{i}: {note}")

    out = ROOT / "runs" / "try_condition" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "baseline": args.baseline,
        "sets": {n: [{**{k: v for k, v in r.items() if k != "condition"}, "condition": r["condition"].model_dump()}
                     for r in runs] for n, runs in results.items()},
    }, indent=2), encoding="utf-8")
    print(f"\nsaved {out.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the condition stage live on photo sets.")
    parser.add_argument("paths", nargs="+", type=Path, help="folders of photos")
    parser.add_argument("--baseline", default=None, help="optional clean product photo to compare against")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    missing = [p for p in args.paths if not p.is_dir()]
    if missing:
        print("Not a folder: " + ", ".join(map(str, missing)), file=sys.stderr)
        return 1
    sys.stdout.reconfigure(errors="backslashreplace")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
