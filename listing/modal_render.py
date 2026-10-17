"""Modal app that renders splats on a GPU for the render stage (RENDER_BACKEND=modal).

Deploy from listing/: modal deploy modal_render.py
The stage calls the deployed function by name. The .ply goes up as bytes and the PNGs come back as bytes.
No warm containers: each call cold-starts a container, which shuts down 2 s after the render.
"""

from __future__ import annotations

import time

import modal

APP_NAME = "mint-listing-render"
FUNCTION_NAME = "render_splat"

# Same versions as the local venv, so both backends run the same torch build.
image = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install("torch==2.11.0", index_url="https://download.pytorch.org/whl/cu128")
    .pip_install("numpy==2.5.4", "pillow==13.0.0")
    .add_local_python_source("splat_render")
)

app = modal.App(APP_NAME, image=image)


@app.function(gpu="L4", timeout=300, scaledown_window=2)
def render_splat(
    ply: bytes, up_axis: str, angles: list[tuple[float, float]], size: int, background_rgb: tuple[int, int, int]
) -> list[bytes]:
    import splat_render

    start = time.perf_counter()
    pngs = splat_render.render_pngs(ply, up_axis, angles, size, background_rgb)
    print(f"rendered {len(pngs)} views in {time.perf_counter() - start:.1f} s")
    return pngs
