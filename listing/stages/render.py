"""render: splat -> 12 labelled square views on a neutral grey background, plus a contact sheet.

Fixture items that have stubs/render.json stay offline. Otherwise splat_render runs on the backend named by
RENDER_BACKEND in .env: "modal" (default; the deployed app in modal_render.py, on a GPU) or "local" (this
machine, CUDA if available). Either way the PNGs come back here, and views go to runs/<item>/views/, the
contact sheet to runs/<item>/contact_sheet.png for checking the render by eye.
lift_masks sends the highlight stage's defect masks to the same backend (splat_render.lift_masks).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image as PILImage, ImageDraw, ImageFont

from contracts import RunContext, View, Views
from images import fit_for_jev
from stages._fixture import has_stub, load_stub

LISTING_ROOT = Path(__file__).resolve().parent.parent

BACKENDS = ("modal", "local")  # the first is the default

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


class RenderBackendError(RuntimeError):
    pass


def view_label(azimuth: int, elevation: int) -> str:
    return f"{AZIMUTH_NAMES[azimuth]}, {elevation}° above"


def _relative(path: Path) -> str:
    try:
        return path.relative_to(LISTING_ROOT).as_posix()
    except ValueError:
        return str(path)


def render_backend() -> str:
    load_dotenv(LISTING_ROOT.parent / ".env")  # the repo-wide .env
    backend = os.environ.get("RENDER_BACKEND", "").strip() or BACKENDS[0]
    if backend not in BACKENDS:
        raise RenderBackendError(f"RENDER_BACKEND must be one of {', '.join(BACKENDS)}, got {backend!r}")
    return backend


def call_modal(function_name: str, *args):
    """Calls a function of the deployed modal_render app (render_splat, lift_splat_masks)."""
    import modal

    from modal_render import APP_NAME

    try:
        return modal.Function.from_name(APP_NAME, function_name).remote(*args)
    except modal.exception.AuthError as e:
        raise RenderBackendError("not logged in to Modal: run `modal setup`, or set RENDER_BACKEND=local") from e
    except modal.exception.NotFoundError as e:
        raise RenderBackendError(
            f"Modal app {APP_NAME} isn't deployed: run `modal deploy modal_render.py` from listing/"
        ) from e


def render_pngs(ply: bytes, up_axis: str, angles: list[tuple[int, int]]) -> list[bytes]:
    args = (ply, up_axis, angles, RENDER["size_px"], RENDER["background_rgb"])
    if render_backend() == "local":
        import splat_render

        return splat_render.render_pngs(*args)
    from modal_render import FUNCTION_NAME

    return call_modal(FUNCTION_NAME, *args)


def lift_masks(splat: bytes, up_axis: str, angles: list[tuple[float, float]], masks: list, size: int) -> dict:
    """splat_render.lift_masks on the RENDER_BACKEND, with the render stage's background."""
    args = (splat, up_axis, angles, masks, size, RENDER["background_rgb"])
    if render_backend() == "local":
        import splat_render

        return splat_render.lift_masks(*args)
    from modal_render import LIFT_FUNCTION_NAME

    return call_modal(LIFT_FUNCTION_NAME, *args)


def render_views(splat_path: Path, item_id: str, up_axis: str, out_dir: Path) -> Views:
    if not splat_path.is_file():
        raise FileNotFoundError(f"no splat at {splat_path}; pass the item folder (with splat.spz or splat.ply) or the splat file itself")
    angles = [(azimuth, elevation) for elevation, azimuths in RENDER["rings"] for azimuth in azimuths]
    pngs = render_pngs(splat_path.read_bytes(), up_axis, angles)
    out_dir.mkdir(parents=True, exist_ok=True)

    views = []
    for i, ((azimuth, elevation), png) in enumerate(zip(angles, pngs, strict=True)):
        view_id = f"v{i:02d}"
        path = out_dir / f"{view_id}.png"
        path.write_bytes(fit_for_jev(png).data)  # checks Jev's limits; unchanged at 1024 px
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
