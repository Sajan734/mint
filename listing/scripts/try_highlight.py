"""Run only the highlight stage on a finished pipeline run (no Jev calls; Gemini and the render backend are live).

    python scripts/try_highlight.py samples [--min-score 0.5] [--up-axis +y]

Reads runs/<item>/render.json, identify.json, condition.json and baseline_lookup.json, and the item folder's splat
and input.json. --min-score highlights every defect condition scored at least this high (default: the threshold
finalize notes defects at, which is higher when no baseline photo was found), to exercise real scans whose defects
sit just under it.
Output: runs/try_highlight/<item>/ (splat_highlighted.*, highlight_sheet.png, highlight/, highlight_raw.json,
highlight.json). Render the highlighted splat from all 12 views with scripts/try_render.py to check its back.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import splat_render  # noqa: E402
from contracts import Baseline, Condition, Identity, Views  # noqa: E402
from pipeline import RUNS_ROOT, item_input, resolve_item, write_json  # noqa: E402
from stages.finalize import PRICE, noted_defects  # noqa: E402
from stages.highlight import make_highlight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the highlight stage alone on a finished run.")
    parser.add_argument("item", type=Path, help="item folder (e.g. samples/<scan_id>) or its splat file")
    parser.add_argument("--min-score", type=float, default=None,
                        help=f"lowest defect score to highlight (default {PRICE['defect_min_score']}, or "
                             f"{PRICE['defect_min_score_no_baseline']} without a baseline photo)")
    parser.add_argument("--up-axis", choices=list(splat_render.AXES), default=None)
    args = parser.parse_args()

    item_dir, splat = resolve_item(args.item)
    run_dir = RUNS_ROOT / item_dir.name
    try:
        views = Views.model_validate_json((run_dir / "render.json").read_text(encoding="utf-8"))
        identity = Identity.model_validate_json((run_dir / "identify.json").read_text(encoding="utf-8"))
        condition = Condition.model_validate_json((run_dir / "condition.json").read_text(encoding="utf-8"))
        baseline = Baseline.model_validate_json((run_dir / "baseline_lookup.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        print(f"{e.filename} is missing: run `python pipeline.py {args.item}` first", file=sys.stderr)
        return 1
    if args.min_score is None:
        defects = noted_defects(condition.defects, baseline.image_path is not None)
    else:
        defects = sorted((d for d in condition.defects if d.score >= args.min_score), key=lambda d: -d.score)
    up_axis = args.up_axis or item_input(item_dir).get("up_axis", "+y")
    out = RUNS_ROOT / "try_highlight" / item_dir.name
    print(f"highlighting {', '.join(f'{d.kind} {d.score:.2f} {d.view_ids}' for d in defects) or 'nothing'}",
          file=sys.stderr)

    result = asyncio.run(make_highlight(splat, up_axis, views, baseline, defects, out, identity=identity))
    write_json(out / "highlight.json", result)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
