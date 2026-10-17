"""render: splat -> 12 PNG views. Stub: returns fixture views."""

from __future__ import annotations

from pathlib import Path

from contracts import RunContext, Views
from stages._fixture import load_stub

RENDER = {
    "size_px": 1024,
    "background_rgb": (128, 128, 128),
    "rings": [  # (elevation_deg, azimuth count)
        (10, 8),
        (40, 4),
    ],
}


async def render(ctx: RunContext, splat_path: Path) -> Views:
    # TODO: rasterize splat_path with RENDER settings.
    return load_stub(ctx, "render", Views)
