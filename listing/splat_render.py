"""Render a trained 3D Gaussian splat (standard 3DGS .ply) from any orbit camera, in plain PyTorch.

Standalone on purpose: it imports nothing from the listing pipeline, so a Modal job can call it as is.
Runs on CUDA when available, otherwise on the CPU (much slower). Colours use the SH DC term only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

SH_C0 = 0.28209479177387814  # degree-0 spherical-harmonic constant

FRAMING = {
    "min_opacity": 0.5,  # only fairly solid Gaussians decide the centre and size
    "radius_quantile": 0.95,  # robust radius: floaters beyond this don't stretch the frame
    "crop_factor": 1.6,  # Gaussians farther than crop_factor * radius from the centre aren't rendered
}

RASTER = {
    "distance_factor": 3.0,  # camera distance in robust radii (mild perspective)
    "fill": 0.85,  # the item's projected extent fills this share of the frame
    "extent_quantiles": (0.02, 0.98),  # projected extent ignores the outermost 2% of Gaussians
    "tile_px": 32,
    "chunk": 2048,  # Gaussians composited per step within a tile
    "min_alpha": 1 / 255,
    "max_alpha": 0.99,
    "stop_transmittance": 1e-4,
    "blur_px2": 0.3,  # low-pass added to every 2D covariance (standard 3DGS anti-aliasing)
}

AXES = {
    "+x": (1.0, 0.0, 0.0), "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0), "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0), "-z": (0.0, 0.0, -1.0),
}


class SplatError(Exception):
    pass


@dataclass(frozen=True)
class Splat:
    means: torch.Tensor  # (N, 3)
    scales: torch.Tensor  # (N, 3), linear
    quats: torch.Tensor  # (N, 4), w x y z, unit length
    opacities: torch.Tensor  # (N,)
    colors: torch.Tensor  # (N, 3), RGB 0..1

    def subset(self, keep: torch.Tensor) -> Splat:
        return Splat(self.means[keep], self.scales[keep], self.quats[keep], self.opacities[keep], self.colors[keep])


@dataclass(frozen=True)
class Framing:
    center: torch.Tensor  # (3,)
    radius: float


@dataclass(frozen=True)
class Camera:
    rotation: torch.Tensor  # (3, 3) world -> camera, rows = right, down, forward (OpenCV)
    position: torch.Tensor  # (3,)


def default_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


# --- loading ----------------------------------------------------------------------------------

REQUIRED_FIELDS = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                   "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]


def _read_header(data: bytes, path: Path) -> tuple[int, list[str], int]:
    """Returns (vertex count, float property names, header length in bytes)."""
    end = data.find(b"end_header\n")
    if not data.startswith(b"ply") or end < 0:
        raise SplatError(f"{path} is not a PLY file")
    lines = data[:end].decode("ascii", errors="replace").splitlines()
    if "format binary_little_endian 1.0" not in lines:
        raise SplatError(f"{path}: only binary little-endian PLY is supported (export it from the trainer as such)")
    count, names = 0, []
    for line in lines:
        parts = line.split()
        if parts[:2] == ["element", "vertex"]:
            count = int(parts[2])
        elif parts[:1] == ["element"]:
            raise SplatError(f"{path}: unexpected element {parts[1]!r}; expected a Gaussian splat with vertices only")
        elif parts[:1] == ["property"]:
            if parts[1] != "float":
                raise SplatError(f"{path}: property {parts[-1]!r} is {parts[1]}, expected float")
            names.append(parts[2])
    missing = [f for f in REQUIRED_FIELDS if f not in names]
    if missing:
        raise SplatError(f"{path} is not a 3DGS splat: missing {', '.join(missing)}")
    return count, names, end + len(b"end_header\n")


def load_ply(path: Path, device: torch.device) -> Splat:
    data = Path(path).read_bytes()
    count, names, offset = _read_header(data, Path(path))
    rows = np.frombuffer(data, dtype=np.dtype([(n, "<f4") for n in names]), count=count, offset=offset)

    def cols(*fields: str) -> torch.Tensor:
        return torch.from_numpy(np.stack([rows[f] for f in fields], axis=1).astype(np.float32)).to(device)

    quats = cols("rot_0", "rot_1", "rot_2", "rot_3")
    return Splat(
        means=cols("x", "y", "z"),
        scales=torch.exp(cols("scale_0", "scale_1", "scale_2")),
        quats=quats / quats.norm(dim=1, keepdim=True).clamp_min(1e-12),
        opacities=torch.sigmoid(cols("opacity")[:, 0]),
        colors=(0.5 + SH_C0 * cols("f_dc_0", "f_dc_1", "f_dc_2")).clamp(0.0, 1.0),
    )


# --- framing and cameras ----------------------------------------------------------------------


def robust_framing(splat: Splat) -> Framing:
    solid = splat.means[splat.opacities >= FRAMING["min_opacity"]]
    if len(solid) < 100:
        raise SplatError(f"only {len(solid)} solid Gaussians; the splat looks empty or untrained")
    center = solid.median(dim=0).values
    distances = (solid - center).norm(dim=1)
    return Framing(center=center, radius=float(torch.quantile(distances, FRAMING["radius_quantile"])))


def crop_floaters(splat: Splat, framing: Framing) -> Splat:
    keep = (splat.means - framing.center).norm(dim=1) <= framing.radius * FRAMING["crop_factor"]
    return splat.subset(keep)


def axis(name: str, device: torch.device) -> torch.Tensor:
    if name not in AXES:
        raise SplatError(f"unknown axis {name!r}; use one of {', '.join(AXES)}")
    return torch.tensor(AXES[name], device=device)


def front_axis(up: str) -> str:
    """Azimuth 0 looks at the item from this side: +z, or +x when up is along z."""
    return "+x" if up.endswith("z") else "+z"


def orbit_camera(framing: Framing, up: str, azimuth_deg: float, elevation_deg: float) -> Camera:
    device = framing.center.device
    up_v, front_v = axis(up, device), axis(front_axis(up), device)
    right_v = torch.linalg.cross(up_v, front_v)  # the viewer's right when standing at the front
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    direction = math.cos(el) * (math.cos(az) * front_v + math.sin(az) * right_v) + math.sin(el) * up_v
    position = framing.center + direction * framing.radius * RASTER["distance_factor"]
    forward = -direction
    right = torch.linalg.cross(forward, up_v)
    right = right / right.norm()
    down = torch.linalg.cross(forward, right)
    return Camera(rotation=torch.stack([right, down, forward]), position=position)


# --- rasterization ----------------------------------------------------------------------------


def _quat_to_rotmat(q: torch.Tensor) -> torch.Tensor:
    w, x, y, z = q.unbind(1)
    return torch.stack([
        1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
        2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
        2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y),
    ], dim=1).reshape(-1, 3, 3)


def _intrinsics(points_cam: torch.Tensor, size: int) -> tuple[float, float, float]:
    """Focal length and principal point that centre the item and make it fill RASTER['fill'] of the frame."""
    lo_q, hi_q = RASTER["extent_quantiles"]
    u = points_cam[:, 0] / points_cam[:, 2]
    v = points_cam[:, 1] / points_cam[:, 2]
    qs = torch.tensor([lo_q, hi_q], device=points_cam.device)
    u_lo, u_hi = torch.quantile(u, qs).tolist()
    v_lo, v_hi = torch.quantile(v, qs).tolist()
    focal = RASTER["fill"] * size / max(u_hi - u_lo, v_hi - v_lo)
    return focal, size / 2 - focal * (u_lo + u_hi) / 2, size / 2 - focal * (v_lo + v_hi) / 2


def _project(splat: Splat, camera: Camera, size: int) -> dict[str, torch.Tensor]:
    p_cam = (splat.means - camera.position) @ camera.rotation.T
    in_front = p_cam[:, 2] > 0.05 * p_cam[:, 2].abs().max()
    s = splat.subset(in_front)
    p_cam = p_cam[in_front]
    focal, cx, cy = _intrinsics(p_cam, size)

    x, y, z = p_cam.unbind(1)
    rot = _quat_to_rotmat(s.quats)
    m = rot * s.scales[:, None, :]
    cov3d = m @ m.transpose(1, 2)
    zeros = torch.zeros_like(z)
    jac = torch.stack([focal / z, zeros, -focal * x / z**2, zeros, focal / z, -focal * y / z**2], 1).reshape(-1, 2, 3)
    t = jac @ camera.rotation
    cov2d = t @ cov3d @ t.transpose(1, 2)
    a = cov2d[:, 0, 0] + RASTER["blur_px2"]
    b = cov2d[:, 0, 1]
    c = cov2d[:, 1, 1] + RASTER["blur_px2"]
    det = (a * c - b * b).clamp_min(1e-12)
    mid = 0.5 * (a + c)
    radius = 3.0 * torch.sqrt(mid + torch.sqrt((mid * mid - det).clamp_min(0.1)))

    order = torch.argsort(z)  # front to back
    return {
        "u": (focal * x / z + cx)[order], "v": (focal * y / z + cy)[order],
        "conic_a": (c / det)[order], "conic_b": (-b / det)[order], "conic_c": (a / det)[order],
        "radius": radius[order], "opacity": s.opacities[order], "color": s.colors[order],
    }


def _composite_tile(g: dict[str, torch.Tensor], px: torch.Tensor, py: torch.Tensor,
                    background: torch.Tensor) -> torch.Tensor:
    """Front-to-back alpha compositing of depth-sorted Gaussians over one tile's pixels."""
    color = torch.zeros(len(px), 3, device=px.device)
    trans = torch.ones(len(px), device=px.device)
    for start in range(0, len(g["u"]), RASTER["chunk"]):
        sl = slice(start, start + RASTER["chunk"])
        dx = px[:, None] - g["u"][None, sl]
        dy = py[:, None] - g["v"][None, sl]
        power = -0.5 * (g["conic_a"][sl] * dx * dx + g["conic_c"][sl] * dy * dy) - g["conic_b"][sl] * dx * dy
        alpha = (g["opacity"][sl] * torch.exp(power.clamp_max(0.0))).clamp_max(RASTER["max_alpha"])
        alpha = torch.where(alpha < RASTER["min_alpha"], torch.zeros_like(alpha), alpha)
        one_minus = 1.0 - alpha
        before = torch.cumprod(torch.cat([torch.ones_like(one_minus[:, :1]), one_minus[:, :-1]], 1), 1)
        weights = alpha * before * trans[:, None]
        color += weights @ g["color"][sl]
        trans = trans * one_minus.prod(1)
        if float(trans.max()) < RASTER["stop_transmittance"]:
            break
    return color + trans[:, None] * background


def render(splat: Splat, camera: Camera, size: int, background_rgb: tuple[int, int, int]) -> np.ndarray:
    """Renders one square view. Returns an (size, size, 3) uint8 RGB image."""
    tile = RASTER["tile_px"]
    if size % tile:
        raise SplatError(f"render size {size} must be a multiple of the {tile} px tile")
    g = _project(splat, camera, size)
    device = g["u"].device
    tiles = size // tile
    background = torch.tensor(background_rgb, device=device, dtype=torch.float32) / 255
    image = background.expand(size, size, 3).clone()
    # Tile ranges each Gaussian touches; off-screen Gaussians get an empty range (start > end).
    tx0 = ((g["u"] - g["radius"]) // tile).clamp(0, tiles)
    tx1 = ((g["u"] + g["radius"]) // tile).clamp(-1, tiles - 1)
    ty0 = ((g["v"] - g["radius"]) // tile).clamp(0, tiles)
    ty1 = ((g["v"] + g["radius"]) // tile).clamp(-1, tiles - 1)
    offsets = torch.arange(tile, device=device, dtype=torch.float32) + 0.5
    for j in range(tiles):
        in_row = torch.nonzero((ty0 <= j) & (ty1 >= j)).squeeze(1)
        for i in range(tiles):
            idx = in_row[(tx0[in_row] <= i) & (tx1[in_row] >= i)]
            if len(idx) == 0:
                continue
            gy, gx = torch.meshgrid(j * tile + offsets, i * tile + offsets, indexing="ij")
            tile_g = {k: v[idx] for k, v in g.items()}
            pixels = _composite_tile(tile_g, gx.reshape(-1), gy.reshape(-1), background)
            image[j * tile:(j + 1) * tile, i * tile:(i + 1) * tile] = pixels.reshape(tile, tile, 3)
    return (image.clamp(0, 1) * 255 + 0.5).to(torch.uint8).cpu().numpy()
