"""load_photos: the item folder's photos -> Views (local, no API).

Input: <item>/photos/*.jpg|jpeg|png|webp, in name order (normally 8, the product from different angles), and
optionally input.json "photo_urls": public URLs of the same photos in the same order (Lens needs a public URL).
Each photo is turned upright from its EXIF orientation, shrunk to PHOTOS["max_side_px"] on its long side and saved
as JPEG to runs/<item>/views/p01.jpg, ... That one size serves every later call: Gemini can still read printed text
and Jev's limits (280-1568 px a side) hold, while a 4032 px phone original would only make every request slower.
Fixture items that have stubs/load_photos.json stay offline.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from PIL import Image as PILImage, ImageOps

from contracts import RunContext, View, Views
from stages._fixture import has_stub, load_stub

LISTING_ROOT = Path(__file__).resolve().parent.parent

PHOTOS = {
    "folder": "photos",
    "suffixes": (".jpg", ".jpeg", ".png", ".webp"),
    "max_side_px": 1024,
    "min_side_px": 280,  # smaller photos can't be judged (and Jev refuses them)
    "jpeg_quality": 90,
    "max_photos": 12,
}


class PhotoError(ValueError):
    pass


def photo_files(item_dir: Path) -> list[Path]:
    folder = item_dir / PHOTOS["folder"]
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in PHOTOS["suffixes"]) if folder.is_dir() else []
    if not files:
        raise PhotoError(f"no photos in {folder}: put the item's JPGs there ({', '.join(PHOTOS['suffixes'])})")
    return files[: PHOTOS["max_photos"]]


def prepare(data: bytes) -> bytes:
    """Upright, at most max_side_px on the long side, JPEG."""
    with PILImage.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        if min(img.size) < PHOTOS["min_side_px"]:
            raise PhotoError(f"photo is {img.size[0]}x{img.size[1]}: each side needs {PHOTOS['min_side_px']} px")
        img.thumbnail((PHOTOS["max_side_px"], PHOTOS["max_side_px"]), PILImage.Resampling.LANCZOS)
        if min(img.size) < PHOTOS["min_side_px"]:  # a very long, thin photo: keep the short side usable
            scale = PHOTOS["min_side_px"] / min(img.size)
            img = img.resize((round(img.size[0] * scale), round(img.size[1] * scale)), PILImage.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=PHOTOS["jpeg_quality"])
        return out.getvalue()


def _relative(path: Path) -> str:
    try:
        return path.relative_to(LISTING_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_views(item_dir: Path, item_id: str, out_dir: Path, photo_urls: list[str] | None = None) -> Views:
    files = photo_files(item_dir)
    urls = list(photo_urls or [])
    out_dir.mkdir(parents=True, exist_ok=True)
    views = []
    for i, path in enumerate(files):
        view_id = f"p{i + 1:02d}"
        target = out_dir / f"{view_id}.jpg"
        try:
            target.write_bytes(prepare(path.read_bytes()))
        except (OSError, PILImage.UnidentifiedImageError) as e:
            raise PhotoError(f"can't read photo {path.name}: {e}") from e
        url = urls[i] if i < len(urls) and isinstance(urls[i], str) and urls[i].startswith("https://") else None
        views.append(View(view_id=view_id, label=f"photo {i + 1}", image_path=_relative(target), source_url=url))
    return Views(item_id=item_id, views=views)


async def load_photos(ctx: RunContext, photo_urls: list[str] | None = None, files: list | None = None) -> Views:
    """files (the photos' names and sizes) only keys the demo cache, so changed photos are a miss."""
    if has_stub(ctx, "load_photos"):
        return load_stub(ctx, "load_photos", Views)
    return await asyncio.to_thread(load_views, ctx.item_dir, ctx.item_id, ctx.run_dir / "views", photo_urls)
