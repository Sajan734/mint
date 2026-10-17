"""render: splat -> 12 labelled square views on a neutral grey background, plus a contact sheet.

Fixture items that have stubs/render.json stay offline. Otherwise the splat is rendered locally with
splat_render (CUDA if available). Views go to runs/<item>/views/, the contact sheet to
runs/<item>/contact_sheet.png for checking the render by eye.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from PIL import Image as PILImage, ImageDraw, ImageFont

import splat_render
from contracts import RunContext, View, Views
from images import fit_for_jev
from stages._fixture import has_stub, load_stub

LISTING_ROOT = Path(__file__).resolve().parent.parent

RENDER = {
    "size_px": 1024,
    "background_rgb": (128, 128, 128),
    "rings": [  # (elevation_deg, azimuths_deg)
        (10, [0, 45, 90, 135, 180, 225, 270, 315]),
        (40, [0, 90, 180, 270]),
    ],
}

AZIMUTH_NAMES = {
    0: "front", 45: "front-right", 90: "right", 135: "back-right",
    180: "back", 225: "back-left", 270: "left", 315: "front-left",
}

SHEET = {"columns": 4, "thumb_px": 320, "label_px": 34, "font_px": 18, "background_rgb": (32, 32, 32)}


def view_label(azimuth: int, elevation: int) -> str:
    return f"{AZIMUTH_NAMES[azimuth]}, {elevation}° above"


def _relative(path: Path) -> str:
    try:
        return path.relative_to(LISTING_ROOT).as_posix()
    except ValueError:
        return str(path)


def _png_bytes(pixels) -> bytes:
    buf = io.BytesIO()
    PILImage.fromarray(pixels).save(buf, format="PNG")
    return buf.getvalue()


def render_views(splat_path: Path, item_id: str, up_axis: str, out_dir: Path) -> Views:
    if not splat_path.is_file():
        raise FileNotFoundError(f"no splat at {splat_path}; pass the item folder (with splat.ply) or the .ply itself")
    device = splat_render.default_device()
    splat = splat_render.load_ply(splat_path, device)
    framing = splat_render.robust_framing(splat)
    splat = splat_render.crop_floaters(splat, framing)
    out_dir.mkdir(parents=True, exist_ok=True)

    views = []
    for elevation, azimuths in RENDER["rings"]:
        for azimuth in azimuths:
            view_id = f"v{len(views):02d}"
            camera = splat_render.orbit_camera(framing, up_axis, azimuth, elevation)
            pixels = splat_render.render(splat, camera, RENDER["size_px"], RENDER["background_rgb"])
            path = out_dir / f"{view_id}.png"
            path.write_bytes(fit_for_jev(_png_bytes(pixels)).data)  # checks Jev's limits; unchanged at 1024 px
            views.append(View(view_id=view_id, label=view_label(azimuth, elevation), azimuth_deg=azimuth,
                              elevation_deg=elevation, image_path=_relative(path)))
    return Views(item_id=item_id, views=views)


def contact_sheet(views: Views, path: Path) -> None:
    """All views in a grid with their ids and labels, for checking the render by eye."""
    thumb, label_h, cols = SHEET["thumb_px"], SHEET["label_px"], SHEET["columns"]
    rows = -(-len(views.views) // cols)
    sheet = PILImage.new("RGB", (cols * thumb, rows * (thumb + label_h)), SHEET["background_rgb"])
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=SHEET["font_px"])
    for i, view in enumerate(views.views):
        x, y = (i % cols) * thumb, (i // cols) * (thumb + label_h)
        with PILImage.open(LISTING_ROOT / view.image_path) as img:
            sheet.paste(img.convert("RGB").resize((thumb, thumb)), (x, y))
        draw.text((x + 8, y + thumb + 6), f"{view.view_id}  {view.label}", fill=(235, 235, 235), font=font)
    sheet.save(path)


async def render(ctx: RunContext, splat_path: Path) -> Views:
    if has_stub(ctx, "render"):
        return load_stub(ctx, "render", Views)
    views = await asyncio.to_thread(render_views, Path(splat_path), ctx.item_id, ctx.up_axis, ctx.run_dir / "views")
    contact_sheet(views, ctx.run_dir / "contact_sheet.png")
    return views
