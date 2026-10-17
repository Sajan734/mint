"""Image normalisation for Jev (rejects, never resizes, so we do the resizing)."""

import io

from PIL import Image, ImageOps

from buyer_agent.errors import AgentError, ErrorCode

MIN_SIDE = 280
MAX_PIXELS_IN = 16_000_000  # decompression-bomb guard on the decoded size
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_REQUEST_BYTES = 32 * 1024 * 1024
JEV_MAX_PIXELS = 2_458_624
_ALLOWED = {"PNG", "JPEG"}


def _bad(detail: str) -> AgentError:
    return AgentError(ErrorCode.IMAGE_INVALID, detail)


def _open(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in _ALLOWED:
            raise _bad(f"unsupported format {img.format}")
        if img.width * img.height > MAX_PIXELS_IN:
            raise _bad("image too large to decode")
        img.load()
    except AgentError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise _bad(f"cannot decode image: {type(e).__name__}") from e
    return img


def normalise_png(data: bytes, max_side: int = 1024) -> bytes:
    """Upright (EXIF applied), RGB, longest side <= max_side, PNG. Raises IMAGE_INVALID."""
    img = ImageOps.exif_transpose(_open(data)).convert("RGB")
    scale = max_side / max(img.size)
    if scale < 1:
        img = img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
    if min(img.size) < MIN_SIDE:
        raise _bad(f"short side {min(img.size)} < {MIN_SIDE}")
    if img.width * img.height > JEV_MAX_PIXELS:
        raise _bad("too many pixels for Jev")
    out = io.BytesIO()
    img.save(out, format="PNG")
    png = out.getvalue()
    if len(png) > MAX_IMAGE_BYTES:
        raise _bad("png over 16 MiB")
    return png


def check_request_bytes(images: list[bytes]) -> None:
    if sum(len(i) for i in images) > MAX_REQUEST_BYTES:
        raise AgentError(ErrorCode.PAYLOAD_TOO_LARGE, "images over 32 MiB per request")


def thumbnail_png(data: bytes, max_side: int) -> bytes:
    """Small PNG for logs. Skips the Jev size rules; still bounded by the decode guard."""
    img = ImageOps.exif_transpose(_open(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
