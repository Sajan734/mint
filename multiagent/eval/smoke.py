"""Smoke test: run one comparison through the real API code with live Jev and Groq.

Usage (from multiagent/, needs the keys in .env):
    python -m eval.smoke --list
    python -m eval.smoke                                   # changed pair + missing-accessory claims
    python -m eval.smoke --case pots1_same --listing pots_truthful
    python -m eval.smoke --folders path/to/seller_imgs path/to/buyer_imgs --name mine
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

from PIL import Image

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
MIN_PAIRS = 12
MAX_SIDE = 1024


def out(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def stage_mock_claims(data_root: Path) -> None:
    """Copy the mock claims files into DATA_ROOT/claims so listing ids resolve."""
    target = data_root / "claims"
    target.mkdir(parents=True, exist_ok=True)
    for src in (PACKAGE_ROOT / "mock" / "claims").glob("*.json"):
        if not (target / src.name).exists():
            shutil.copy(src, target / src.name)


def list_cases(data_root: Path) -> None:
    out("Cases (--case):")
    for p in sorted((data_root / "paslcd_pairs").glob("*/pairs.json")):
        out(f"  {p.parent.name}")
    out("Listings with claims (--listing):")
    for p in sorted((data_root / "claims").glob("*.json")):
        out(f"  {p.stem}")


def build_pairs_from_folders(data_root: Path, a_dir: Path, b_dir: Path, name: str) -> str:
    """Pair sorted images from two folders and write a manifest under DATA_ROOT."""
    a = sorted(p for p in a_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    b = sorted(p for p in b_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    n = min(len(a), len(b), 24)
    if n < MIN_PAIRS:
        raise SystemExit(
            f"Need at least {MIN_PAIRS} images in each folder (found {len(a)}, {len(b)})."
        )
    folder = data_root / "user_pairs" / name
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for i in range(n):
        entry = {"label": f"view_{i + 1:02d}"}
        for side, src in (("a", a[i]), ("b", b[i])):
            img = Image.open(src).convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            dest = folder / f"view_{i + 1:02d}_{side}.png"
            img.save(dest)
            entry[side] = dest.relative_to(data_root).as_posix()
        items.append(entry)
    (folder / "pairs.json").write_text(json.dumps(items, indent=1), encoding="utf-8")
    return (folder / "pairs.json").relative_to(data_root).as_posix()


def show(d: dict) -> None:
    verdict = d.get("verdict") or {}
    out(f"status        : {d.get('status')}")
    out(f"verdict       : {verdict.get('label')}   evidence score: {verdict.get('evidence_score')}")
    out(f"why           : {verdict.get('reason')}")
    ev = verdict.get("evidence") or {}
    out(f"views         : {ev.get('answered_views')} answered, {ev.get('usable_views')} usable")
    for cat, c in (ev.get("categories") or {}).items():
        out(f"  {cat:11s} evidence {c['evidence']:.2f}  (max {c['max']:.2f})")
    for note in verdict.get("caveats") or []:
        out(f"caveat        : {note}")
    for f in d.get("claims_findings") or []:
        out(f"claim         : {f['claim']!r} -> {f['status']}")
    step = d.get("next_step") or {}
    out(
        f"next step     : {step.get('category')} (audience: {step.get('audience')}, rule {step.get('reason_code')})"
    )
    out(f"drafted by    : {step.get('drafted_by')}  template: {step.get('is_template')}")
    out(f"summary       : {step.get('summary')}")
    if step.get("message_to_seller"):
        out(f"message       : {step['message_to_seller']}")
    if step.get("refund_request"):
        out(f"refund request: {step['refund_request']}")
    out(f"timings (ms)  : {d.get('timings_ms')}")
    if d.get("error"):
        out(f"error         : {d['error']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--case", default="pots_i1_changed_small+medium")
    ap.add_argument("--listing", default="pots_missing_accessory")
    ap.add_argument("--listing-file", type=Path, help="claims JSON (native or listing format)")
    ap.add_argument("--folders", nargs=2, metavar=("SELLER_DIR", "BUYER_DIR"))
    ap.add_argument("--name", default="mine")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    import os

    os.environ.setdefault("BUYER_AGENT_LIVE", "1")
    from fastapi.testclient import TestClient

    from buyer_agent.api import create_app
    from buyer_agent.config import load_settings

    settings = load_settings()
    stage_mock_claims(settings.data_root)
    if args.listing_file:
        shutil.copy(
            args.listing_file, settings.data_root / "claims" / f"{args.listing_file.stem}.json"
        )
        args.listing = args.listing_file.stem
    if args.list:
        list_cases(settings.data_root)
        return
    if args.folders:
        manifest = build_pairs_from_folders(
            settings.data_root, Path(args.folders[0]), Path(args.folders[1]), args.name
        )
    else:
        manifest = f"paslcd_pairs/{args.case}/pairs.json"
    body = {
        "comparison_id": str(uuid.uuid4()),
        "listing_id": args.listing,
        "view_pairs": {"manifest_path": manifest},
        "attempt": 1,
    }
    token = settings.buyer_agent_token.get_secret_value()
    client = TestClient(create_app(settings))
    out(f"Running {manifest} with listing {args.listing} (live Jev + Groq)...")
    r = client.post("/v1/comparisons", json=body, headers={"Authorization": f"Bearer {token}"})
    out(f"HTTP {r.status_code}")
    show(r.json())


if __name__ == "__main__":
    main()
