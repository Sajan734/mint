"""The 8 reference ("held-out") renders of every finished splat, for the comparison engine, agents and web.

Layout, on a cube centred on the object and yaw-aligned with it (scan frame: +Y up, +X along the
object's long axis):
  - top + bottom captured -> the 8 cube corners (4 upper at +35.3 deg, 4 lower at -35.3 deg)
  - top only              -> 8 points around the cube's top face: its 4 corners (+35.3 deg) and the
                             midpoints of its 4 top edges (+45 deg), every 45 deg of azimuth
  (the underside of a top-only scan was never seen, so no view looks at it)

Each view is written twice: RGBA PNG (transparent background, for the web) and an opaque PNG on the
listing pipeline's mid-grey (for Jev, which takes PNG/JPEG). Cameras go into views.json in the
pipeline's OpenCV convention, so anyone can re-render or compare from exactly the same viewpoint.
"""
import math

import cv2
import numpy as np
import torch

from .train import look_at, render

VIEWS = {
    "size_px": 1024,
    "fov_deg": 40.0,
    "fill": 0.85,  # the object's projected extent fills this share of the frame
    "extent_quantile": 0.99,  # ignore the outermost 1% of Gaussians when framing (stray specks)
    "grey_rgb": (128, 128, 128),  # listing/stages/render.py background
}

CORNER_EL = math.degrees(math.asin(1 / math.sqrt(3)))  # 35.26 deg


def layout(include_bottom: bool) -> list[tuple[float, float]]:
    """(azimuth_deg, elevation_deg) per view. Azimuth is measured in the ground plane from +X toward +Z."""
    if include_bottom:
        return [(az, el) for el in (CORNER_EL, -CORNER_EL) for az in (45, 135, 225, 315)]
    return [(az, CORNER_EL if az % 90 else 45.0) for az in range(0, 360, 45)]


def direction(az_deg: float, el_deg: float) -> torch.Tensor:
    az, el = math.radians(az_deg), math.radians(el_deg)
    return torch.tensor([math.cos(el) * math.cos(az), math.sin(el), math.cos(el) * math.sin(az)], device="cuda")


def fit_distance(pts: torch.Tensor, center: torch.Tensor, d: torch.Tensor, tan_half: float) -> float:
    """Smallest camera distance along d at which the points' projected extent fits fill * frame.

    With the camera at center + dist * d looking at center, a point at depth (dist - a) with lateral
    offsets (x, y) stays in frame when max(|x|, |y|) <= t * (dist - a), i.e. dist >= a + max(|x|,|y|) / t."""
    c2w = look_at(center + d, center)
    rel = pts - center
    a = rel @ d
    lateral = torch.maximum((rel @ c2w[:3, 0]).abs(), (rel @ c2w[:3, 1]).abs())
    need = a + lateral / (VIEWS["fill"] * tan_half)
    return float(need.quantile(VIEWS["extent_quantile"]))


@torch.no_grad()
def reference_views(params, sh_degree: int, include_bottom: bool):
    """Returns ([(file_name, png_bytes)], meta)."""
    size = VIEWS["size_px"]
    half = math.radians(VIEWS["fov_deg"]) / 2
    f = size / 2 / math.tan(half)
    K = torch.tensor([[f, 0, size / 2], [0, f, size / 2], [0, 0, 1.0]], device="cuda")
    solid = params["means"][torch.sigmoid(params["opacities"]) > 0.3]
    solid = solid[torch.randperm(len(solid), device="cuda")[:50_000]]
    center = solid.median(0).values
    zero_bg = torch.zeros(1, 3, device="cuda")
    grey = np.array(VIEWS["grey_rgb"], np.float32) / 255

    files, views = [], []
    for i, (az, el) in enumerate(layout(include_bottom)):
        d = direction(az, el)
        dist = fit_distance(solid, center, d, math.tan(half))
        c2w = look_at(center + dist * d, center)
        rgb, alpha, _ = render(params, torch.linalg.inv(c2w)[None], K[None], size, size, sh_degree, zero_bg)
        a = alpha[0].clamp(0, 1)[..., None]
        premul = rgb[0].clamp(0, 1)
        straight = (premul / a.clamp_min(1e-6)).clamp(0, 1)
        rgba = torch.cat([straight, a], -1).cpu().numpy()
        flat = (premul + (1 - a) * torch.from_numpy(grey).cuda()).cpu().numpy()
        name = f"{i:02d}_az{az:03.0f}_el{el:+03.0f}"
        files.append((f"{name}.png", _png(rgba, cv2.COLOR_RGBA2BGRA)))
        files.append((f"{name}_grey.png", _png(flat, cv2.COLOR_RGB2BGR)))
        views.append({"name": name, "azimuth_deg": round(az, 2), "elevation_deg": round(el, 2),
                      "files": {"transparent": f"{name}.png", "grey": f"{name}_grey.png"},
                      "c2w": c2w.cpu().numpy().round(6).tolist()})

    meta = {"v": 3, "layout": "cube_corners" if include_bottom else "cube_top", "includes_bottom": include_bottom,
            "convention": "OpenCV camera-to-world (x right, y down, z forward); scan frame +Y up, +X along the "
                          "object's long axis, origin under the object; azimuth from +X toward +Z",
            "width": size, "height": size, "K": K.cpu().numpy().round(4).tolist(),
            "center": center.cpu().numpy().round(6).tolist(), "background_grey_rgb": list(VIEWS["grey_rgb"]),
            "views": views}
    return files, meta


def _png(img: np.ndarray, conversion: int) -> bytes:
    return cv2.imencode(".png", cv2.cvtColor((img * 255 + 0.5).astype(np.uint8), conversion))[1].tobytes()
