"""Render a splat's 12 views and contact sheet only (no Gemini or Jev calls), e.g. to find the right up axis.

    python scripts/try_render.py samples/splat.ply [--up-axis -y]

Renders on Modal or locally, per RENDER_BACKEND (see stages/render.py).
Output: runs/try_render/<splat name>/views/*.png and contact_sheet.png.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import splat_render  # noqa: E402
from stages.render import RenderBackendError, contact_sheet, render_backend, render_views  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a splat's 12 views and a contact sheet.")
    parser.add_argument("splat", type=Path, help="3DGS .ply file")
    parser.add_argument("--up-axis", choices=list(splat_render.AXES), default="+y")
    args = parser.parse_args()

    out_dir = ROOT / "runs" / "try_render" / args.splat.stem
    start = time.perf_counter()
    try:
        print(f"backend: {render_backend()}")
        views = render_views(args.splat, args.splat.stem, args.up_axis, out_dir / "views")
    except (splat_render.SplatError, FileNotFoundError, RenderBackendError) as e:
        print(e, file=sys.stderr)
        return 1
    sheet = out_dir / "contact_sheet.png"
    contact_sheet(views, sheet)
    print(f"{len(views.views)} views in {time.perf_counter() - start:.1f} s, up axis {args.up_axis}")
    print(f"contact sheet: {sheet.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
