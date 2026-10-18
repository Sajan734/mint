"""The website's drag-to-spin frames: a 24-frame turntable of the finished splat (transparent WebP).

One elevation (SPIN["elevation_deg"], above the item: a one-pass scan never saw the underside), azimuth 0, 15, ...
345 deg from the item's long axis (+X) toward +Z, all from one distance so the item keeps its size while it spins.
"""
import math

import cv2
import numpy as np
import torch

from .train import look_at, render

SPIN = {
    "frames": 24,  # every 15 deg, what the website's spin viewer uses
    "elevation_deg": 25.0,
    "size_px": 512,
    "fov_deg": 40.0,
    "fill": 0.85,  # the item's projected extent fills this share of the frame
    "extent_quantile": 0.99,  # ignore the outermost 1% of Gaussians when framing (stray specks)
    "webp_quality": 85,
}


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
    need = a + lateral / (SPIN["fill"] * tan_half)
    return float(need.quantile(SPIN["extent_quantile"]))


@torch.no_grad()
def spin_frames(params, sh_degree: int) -> list[tuple[str, bytes]]:
    """[("f00.webp", bytes), ...]."""
    size, el = SPIN["size_px"], SPIN["elevation_deg"]
    half = math.radians(SPIN["fov_deg"]) / 2
    f = size / 2 / math.tan(half)
    K = torch.tensor([[f, 0, size / 2], [0, f, size / 2], [0, 0, 1.0]], device="cuda")
    solid = params["means"][torch.sigmoid(params["opacities"]) > 0.3]
    solid = solid[torch.randperm(len(solid), device="cuda")[:50_000]]
    center = solid.median(0).values
    azimuths = [i * 360 / SPIN["frames"] for i in range(SPIN["frames"])]
    dist = max(fit_distance(solid, center, direction(az, el), math.tan(half)) for az in azimuths)
    frames = []
    for i, az in enumerate(azimuths):
        c2w = look_at(center + dist * direction(az, el), center)
        rgb, alpha, _ = render(params, torch.linalg.inv(c2w)[None], K[None], size, size, sh_degree,
                               torch.zeros(1, 3, device="cuda"))
        a = alpha[0].clamp(0, 1)[..., None]
        straight = (rgb[0].clamp(0, 1) / a.clamp_min(1e-6)).clamp(0, 1)  # render() is premultiplied
        bgra = cv2.cvtColor((torch.cat([straight, a], -1).cpu().numpy() * 255 + 0.5).astype(np.uint8),
                            cv2.COLOR_RGBA2BGRA)
        frames.append((f"f{i:02d}.webp", cv2.imencode(".webp", bgra, [cv2.IMWRITE_WEBP_QUALITY,
                                                                       SPIN["webp_quality"]])[1].tobytes()))
    return frames
