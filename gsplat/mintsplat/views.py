"""Fixed reference renders of the finished splat: one camera at each corner of a cube around the
object, looking at its centre. Downstream (comparison engine, agents, web) gets the same 8 canonical
views for every item, with exact cameras, so they can re-render or compare without guessing poses.
"""
import math

import cv2
import numpy as np
import torch

from .train import look_at, render


@torch.no_grad()
def cube_corners(params, sh_degree: int, size: int = 768, fov_deg: float = 40.0, margin: float = 1.15):
    """Returns ([(name, png_bytes)], meta). PNGs are RGBA (transparent background).

    Cameras are OpenCV (x right, y down, z forward) camera-to-world in the scan frame (+Y up,
    origin on the support plane under the object), same convention as the rest of the pipeline.
    """
    means = params["means"]
    center = means.median(0).values
    radius = float((means - center).norm(dim=1).quantile(0.98))
    half = math.radians(fov_deg) / 2
    dist = radius / math.sin(half) * margin  # bounding sphere fits the frame with a margin
    f = size / 2 / math.tan(half)
    K = torch.tensor([[f, 0, size / 2], [0, f, size / 2], [0, 0, 1.0]], device="cuda")
    zero_bg = torch.zeros(1, 3, device="cuda")

    images, views = [], []
    for sx in (1, -1):
        for sy in (1, -1):
            for sz in (1, -1):
                name = "corner_" + "".join("p" if s > 0 else "n" for s in (sx, sy, sz))  # e.g. corner_pnp
                d = torch.tensor([sx, sy, sz], device="cuda", dtype=torch.float32) / math.sqrt(3)
                c2w = look_at(center + dist * d, center)
                rgb, alpha, _ = render(params, torch.linalg.inv(c2w)[None], K[None], size, size, sh_degree, zero_bg)
                a = alpha[0].clamp(0, 1)
                col = (rgb[0] / a[..., None].clamp_min(1e-6)).clamp(0, 1)  # un-premultiply for straight alpha
                rgba = torch.cat([col, a[..., None]], -1).cpu().numpy()
                png = cv2.imencode(".png", cv2.cvtColor((rgba * 255 + 0.5).astype(np.uint8), cv2.COLOR_RGBA2BGRA))[1]
                images.append((f"{name}.png", png.tobytes()))
                views.append({"name": name, "file": f"{name}.png", "c2w": c2w.cpu().numpy().round(6).tolist()})

    meta = {"v": 3, "convention": "OpenCV camera-to-world (x right, y down, z forward); scan frame +Y up, "
                                  "origin on the support plane under the object",
            "width": size, "height": size, "K": K.cpu().numpy().round(4).tolist(),
            "center": center.cpu().numpy().round(6).tolist(), "radius": round(radius, 6), "views": views}
    return images, meta
