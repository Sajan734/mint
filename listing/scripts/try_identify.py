"""Try the identify stage on a folder of images (real Gemini call).

    python scripts/try_identify.py path/to/folder [--model gemini-...] [--max-views 12]

Images (PNG/JPEG, sorted by file name) are labelled by file name. Prints Gemini's raw answer, what the
evidence rule changed, and the final Identity. Saves everything to runs/try_identify/<folder>-<timestamp>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts import View, Views  # noqa: E402
from stages.identify import MissingKeyError, call_gemini, to_identity  # noqa: E402

SUFFIXES = {".png", ".jpg", ".jpeg"}


def folder_views(folder: Path, max_views: int) -> Views:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUFFIXES)
    if not files:
        raise SystemExit(f"No PNG or JPEG images in {folder}")
    if len(files) > max_views:
        print(f"{len(files)} images found; using the first {max_views}", file=sys.stderr)
        files = files[:max_views]
    return Views(
        item_id=folder.name,
        views=[
            View(view_id=f"v{i:02d}", label=p.stem, azimuth_deg=0, elevation_deg=0, image_path=str(p.resolve()))
            for i, p in enumerate(files)
        ],
    )


async def run(args) -> int:
    views = folder_views(args.folder, args.max_views)
    print(f"{len(views.views)} images from {args.folder}")
    try:
        result = await call_gemini(views, model=args.model)
    except MissingKeyError as e:
        print(e, file=sys.stderr)
        return 2
    identity, notes = to_identity(result.raw)

    print(f"model {result.model} | {result.latency_ms:.0f} ms | tokens in {result.input_tokens} / out {result.output_tokens}")
    for note in result.image_notes:
        print(f"image: {note}")
    print("\nGemini raw answer:")
    print(json.dumps(result.raw, indent=2, ensure_ascii=False))
    print("\nEvidence rule:")
    for note in notes or ["no changes"]:
        print(f"  {note}")
    print("\nIdentity:")
    print(identity.model_dump_json(indent=2))

    out_dir = ROOT / "runs" / "try_identify"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.folder.name}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(
        json.dumps(
            {
                "folder": str(args.folder),
                "images": [v.image_path for v in views.views],
                "model": result.model,
                "latency_ms": round(result.latency_ms),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "image_notes": result.image_notes,
                "raw": result.raw,
                "evidence_notes": notes,
                "identity": identity.model_dump(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved {out.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the identify stage on a folder of images.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--model", default=None, help="Gemini model (default: GEMINI_MODEL or the stage default)")
    parser.add_argument("--max-views", type=int, default=12)
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")  # piped Windows output is cp1252
    if not args.folder.is_dir():
        print(f"Not a folder: {args.folder}", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
