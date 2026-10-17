"""Render both splats on the teammate's deployed Modal function, once per scan, same cameras.

Call shape (listing/modal_render.py): render_splat(ply, up_axis, angles, size, background_rgb)
-> list[PNG bytes], one per (azimuth_deg, elevation_deg) in `angles`, in order. Not wired into
sources.resolve (that Renderer protocol takes aligned clouds, not .ply bytes); call render_pairs
directly with the raw .ply bytes. `modal` is imported lazily and the call is injectable.
"""

from collections.abc import Callable

from buyer_agent.cameras import SIDES
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.models import ViewPair

APP_NAME = "mint-listing-render"  # listing/modal_render.py APP_NAME
FUNCTION_NAME = "render_splat"  # listing/modal_render.py FUNCTION_NAME
# Constants copied from listing/stages/render.py RENDER (not imported on purpose).
SIZE_PX = 1024
BACKGROUND_RGB = (128, 128, 128)
RINGS = ((10, (0, 45, 90, 135, 180, 225, 270, 315)), (40, (0, 90, 180, 270)))
ANGLES: list[tuple[int, int]] = [
    (az, el) for el, azs in RINGS for az in azs
]  # (azimuth, elevation)

RenderCall = Callable[[bytes, str, list[tuple[int, int]], int, tuple[int, int, int]], list[bytes]]


def view_label(azimuth: int, elevation: int) -> str:
    return f"{SIDES[azimuth]} (azimuth {azimuth}°), {elevation}° above"


def modal_call(*args) -> list[bytes]:
    """Real call to the deployed app. Needs `pip install modal` and `modal setup`."""
    try:
        import modal
    except ImportError as exc:
        raise AgentError(ErrorCode.INPUT_INVALID, "modal is not installed") from exc
    return modal.Function.from_name(APP_NAME, FUNCTION_NAME).remote(*args)


def render_pairs(
    ply_a: bytes, ply_b: bytes, up_axis: str = "-y", call: RenderCall | None = None
) -> list[ViewPair]:
    """Listing splat (a) and buyer splat (b) through identical angles, background and up_axis."""
    call = call or modal_call
    args = (up_axis, ANGLES, SIZE_PX, BACKGROUND_RGB)
    pngs_a, pngs_b = call(ply_a, *args), call(ply_b, *args)
    if not len(pngs_a) == len(pngs_b) == len(ANGLES):
        raise AgentError(ErrorCode.INPUT_INVALID, "render returned the wrong number of views")
    return [
        ViewPair(label=view_label(az, el), azimuth_deg=az, elevation_deg=el, png_a=a, png_b=b)
        for (az, el), a, b in zip(ANGLES, pngs_a, pngs_b, strict=True)
    ]
