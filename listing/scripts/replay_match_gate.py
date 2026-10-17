"""Re-apply match gate thresholds to saved per-view Jev answers. No API calls.

    python scripts/replay_match_gate.py [files...] [--set match_min=0.65 --set min_usable_views=5]

Default files: runs/*/match_gate_raw.json and fixtures/*/stubs/match_gate.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stages.match_gate import THRESHOLDS, aggregate, decide, load_raw  # noqa: E402


def parse_overrides(pairs: list[str]) -> dict:
    thresholds = dict(THRESHOLDS)
    for pair in pairs:
        key, _, value = pair.partition("=")
        if key not in thresholds or not value:
            raise SystemExit(f"--set expects one of {', '.join(THRESHOLDS)} as key=value, got {pair!r}")
        thresholds[key] = type(THRESHOLDS[key])(float(value))
    return thresholds


def replay(path: Path, thresholds: dict) -> str:
    raw = load_raw(json.loads(path.read_text(encoding="utf-8")))
    agg = aggregate(raw.views, thresholds)
    verdict, reason = decide(agg, thresholds)
    fmt = lambda x: "  -  " if x is None else f"{x:.3f}"  # noqa: E731
    return (
        f"{verdict:<9} ({reason:<17}) usable {agg.usable_views:>2}/{agg.total_views:<2} "
        f"category {fmt(agg.same_category)}  product {fmt(agg.same_product)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay match gate decisions on saved answers.")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a threshold")
    args = parser.parse_args()
    thresholds = parse_overrides(args.set)
    files = args.files or sorted(ROOT.glob("runs/*/match_gate_raw.json")) + sorted(
        ROOT.glob("fixtures/*/stubs/match_gate.json")
    )
    if not files:
        print("No saved answers found.", file=sys.stderr)
        return 1
    print("thresholds: " + ", ".join(f"{k}={v}" for k, v in thresholds.items()))
    for path in files:
        label = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"{str(label):<42} {replay(path, thresholds)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
