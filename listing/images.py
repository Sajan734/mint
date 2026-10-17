"""Fit images to Jev's limits: PNG or JPEG, each side 280-1568 px, at most 16 MiB, pixels upright."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image as PILImage, ImageOps

JEV_LIMITS = {
    "min_side_px": 280,
    "max_side_px": 1568,
    "max_bytes": 16 * 1024 * 1024,
    "max_pixels": 40_000_000,  # refuse anything bigger before decoding (decompression-bomb guard)
    "jpeg_quality": 92,
}

EXIF_ORIENTATION = 274


class ImageProblem(Exception):
    pass


@dataclass(frozen=True)
class FittedImage:
    data: bytes
    mime: str
    width: int
    height: int
    notes: list[str] = field(default_factory=list)

    @property
    def extension(self) -> str:
        return ".png" if self.mime == "image/png" else ".jpg"


def fit_for_jev(data: bytes) -> FittedImage:
    """Rotates upright, converts to PNG/JPEG and shrinks to fit; rejects images that can't fit."""
    try:
        img = PILImage.open(io.BytesIO(data))
    except Exception as e:  # Pillow raises several types for unreadable data
        raise ImageProblem(f"not a readable image ({type(e).__name__})") from e
    with img:
        w0, h0 = img.size
        if w0 * h0 > JEV_LIMITS["max_pixels"]:
            raise ImageProblem(f"{w0}x{h0} is too large to open safely")
        fmt, out, notes = img.format, img, []
        if img.getexif().get(EXIF_ORIENTATION, 1) != 1:
            out = ImageOps.exif_transpose(img)
            notes.append("rotated upright")
        if fmt not in ("PNG", "JPEG"):
            notes.append(f"converted from {fmt}")
            fmt = "JPEG"
        if max(out.size) > JEV_LIMITS["max_side_px"]:
            w, h = out.size
            out = out.copy()
            out.thumbnail((JEV_LIMITS["max_side_px"], JEV_LIMITS["max_side_px"]), PILImage.Resampling.LANCZOS)
            notes.append(f"shrunk from {w}x{h}")
        width, height = out.size
        if min(width, height) < JEV_LIMITS["min_side_px"]:
            raise ImageProblem(f"{width}x{height}: shorter side is under {JEV_LIMITS['min_side_px']} px")
        if notes:
            buf = io.BytesIO()
            if fmt == "JPEG":
                out.convert("RGB").save(buf, format="JPEG", quality=JEV_LIMITS["jpeg_quality"])
            else:
                out.save(buf, format="PNG")
            data = buf.getvalue()
    if len(data) > JEV_LIMITS["max_bytes"]:
        raise ImageProblem(f"{len(data) / 2**20:.1f} MiB is over 16 MiB")
    return FittedImage(data, "image/png" if fmt == "PNG" else "image/jpeg", width, height, notes)
