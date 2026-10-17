"""Render a trained 3D Gaussian splat (standard 3DGS .ply, or the splat job's .spz) from any orbit camera, in plain PyTorch.

Standalone on purpose: it imports nothing from the listing pipeline, so the Modal app (modal_render.py) runs it
as is. Runs on CUDA when available, otherwise on the CPU (much slower). Colours use the SH DC term only.
Also lifts 2D masks drawn on those renders onto the Gaussians that show through them (lift_masks), and writes a
copy of a splat with chosen Gaussians tinted (tint_splat).
"""

from __future__ import annotations

import gzip
import io
import math
import struct
from dataclasses import dataclass

import numpy as np
import torch
from PIL import Image as PILImage

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

LIFT = {
    "min_hit_px": 1e-3,  # a Gaussian is returned once this much of its blending weight falls inside some mask
    "surface_alpha": 0.2,  # pixels covered less than this have no surface depth (silhouette fringe, background)
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


def _read_header(data: bytes) -> tuple[int, list[str], int]:
    """Returns (vertex count, float property names, header length in bytes)."""
    end = data.find(b"end_header\n")
    if not data.startswith(b"ply") or end < 0:
        raise SplatError("the splat is not a PLY file")
    lines = data[:end].decode("ascii", errors="replace").splitlines()
    if "format binary_little_endian 1.0" not in lines:
        raise SplatError("only binary little-endian PLY is supported (export the splat from the trainer as such)")
    count, names = 0, []
    for line in lines:
        parts = line.split()
        if parts[:2] == ["element", "vertex"]:
            count = int(parts[2])
        elif parts[:1] == ["element"]:
            raise SplatError(f"unexpected PLY element {parts[1]!r}; expected a Gaussian splat with vertices only")
        elif parts[:1] == ["property"]:
            if parts[1] != "float":
                raise SplatError(f"PLY property {parts[-1]!r} is {parts[1]}, expected float")
            names.append(parts[2])
    missing = [f for f in REQUIRED_FIELDS if f not in names]
    if missing:
        raise SplatError(f"the PLY is not a 3DGS splat: missing {', '.join(missing)}")
    return count, names, end + len(b"end_header\n")


def parse_ply(data: bytes, device: torch.device) -> Splat:
    count, names, offset = _read_header(data)
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


# SPZ: Niantic's compressed splat format (gzip container, versions 2 and 3), which the splat job publishes at
# ~1/10 the size of the .ply. Mirrors the reference decoder (nianticlabs/spz, load-spz.cc); only what this renderer
# uses is decoded (no higher-order SH). Version 4 (zstd) is not supported.
SPZ = {"magic": 0x5053474E, "color_scale": 0.15, "sh_dim": {0: 0, 1: 3, 2: 8, 3: 15, 4: 24},
       "sh_zero_byte": 128}  # SH bytes decode as (byte - 128) / 128


def parse_splat(data: bytes, device: torch.device) -> Splat:
    """A .spz (gzip) or a binary .ply, told apart by their first bytes."""
    return parse_spz(data, device) if data[:2] == b"\x1f\x8b" else parse_ply(data, device)


def _spz_payload(data: bytes) -> bytes:
    try:
        return gzip.decompress(data)
    except (OSError, EOFError) as e:
        if data[:4] == struct.pack("<I", SPZ["magic"]):
            raise SplatError("SPZ version 4 (zstd) is not supported; export version 3") from e
        raise SplatError("the splat is neither a PLY nor an SPZ file") from e


def _spz_layout(raw: bytes) -> tuple[int, int, int, dict[str, tuple[int, int]]]:
    """Checks a decompressed SPZ and returns (version, count, fractional bits, {stream: (offset, bytes per
    Gaussian)}) for the streams in the format's fixed order: positions, alphas, colors, scales, rotations, sh."""
    if len(raw) < 16:
        raise SplatError("the SPZ file is truncated")
    magic, version, n, sh_degree, frac_bits = struct.unpack_from("<IIIBB", raw, 0)
    if magic != SPZ["magic"]:
        raise SplatError("not an SPZ file (bad magic)")
    if version not in (2, 3):
        raise SplatError(f"SPZ version {version} is not supported (2 and 3 are)")
    if sh_degree not in SPZ["sh_dim"]:
        raise SplatError(f"SPZ SH degree {sh_degree} is not supported")
    sizes = {"positions": 9, "alphas": 1, "colors": 3, "scales": 3, "rotations": 4 if version >= 3 else 3,
             "sh": SPZ["sh_dim"][sh_degree] * 3}
    if 16 + n * sum(sizes.values()) > len(raw):
        raise SplatError("the SPZ file is truncated")
    offset, streams = 16, {}
    for name, size in sizes.items():
        streams[name] = (offset, size)
        offset += n * size
    return version, n, frac_bits, streams


def parse_spz(data: bytes, device: torch.device) -> Splat:
    raw = _spz_payload(data)
    version, n, frac_bits, layout = _spz_layout(raw)
    # the SH stream is skipped: colours use the DC term only
    streams = {name: np.frombuffer(raw, np.uint8, n * size, offset).reshape(n, size)
               for name, (offset, size) in layout.items() if name != "sh"}

    p = streams["positions"].reshape(n * 3, 3).astype(np.int32)
    fixed = p[:, 0] | (p[:, 1] << 8) | (p[:, 2] << 16)
    fixed = np.where(fixed & 0x800000, fixed - (1 << 24), fixed)  # sign-extend 24-bit fixed point
    means = (fixed.astype(np.float32) / np.float32(1 << frac_bits)).reshape(n, 3)
    dc = (streams["colors"].astype(np.float32) / 255.0 - 0.5) / SPZ["color_scale"]
    quats = torch.from_numpy(_spz_quats(streams["rotations"], version)).to(device)

    def tensor(a: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.ascontiguousarray(a, dtype=np.float32)).to(device)

    return Splat(
        means=tensor(means),
        scales=torch.exp(tensor(streams["scales"].astype(np.float32) / 16.0 - 10.0)),
        quats=quats / quats.norm(dim=1, keepdim=True).clamp_min(1e-12),
        opacities=tensor(streams["alphas"][:, 0].astype(np.float32) / 255.0),
        colors=(0.5 + SH_C0 * tensor(dc)).clamp(0.0, 1.0),
    )


def _spz_quats(r: np.ndarray, version: int) -> np.ndarray:
    """Rotation bytes -> (N, 4) w x y z. v3 packs 'smallest three': 2 bits for the index of the largest x/y/z/w
    component, then 3 x (9-bit magnitude scaled by 1/sqrt(2), 1 sign bit) from the highest other index down.
    v2 stores x, y, z as bytes and w >= 0."""
    if version < 3:
        xyz = r.astype(np.float32) / 127.5 - 1.0
        w = np.sqrt(np.maximum(0.0, 1.0 - (xyz**2).sum(1)))
        return np.concatenate([w[:, None], xyz], 1).astype(np.float32)
    comp = (r[:, 0].astype(np.uint32) | (r[:, 1].astype(np.uint32) << 8) | (r[:, 2].astype(np.uint32) << 16)
            | (r[:, 3].astype(np.uint32) << 24))
    largest = (comp >> 30).astype(np.int64)
    mask = np.uint32((1 << 9) - 1)
    xyzw = np.zeros((len(r), 4), np.float32)
    for i in range(3, -1, -1):
        here = largest != i
        value = np.float32(np.sqrt(0.5)) * (comp & mask).astype(np.float32) / np.float32(mask)
        xyzw[here, i] = np.where(((comp >> 9) & 1).astype(bool), -value, value)[here]
        comp = np.where(here, comp >> 10, comp)
    xyzw[np.arange(len(r)), largest] = np.sqrt(np.maximum(0.0, 1.0 - (xyzw**2).sum(1)))
    return np.concatenate([xyzw[:, 3:], xyzw[:, :3]], 1)


# --- framing and cameras ----------------------------------------------------------------------


def robust_framing(splat: Splat) -> Framing:
    solid = splat.means[splat.opacities >= FRAMING["min_opacity"]]
    if len(solid) < 100:
        raise SplatError(f"only {len(solid)} solid Gaussians; the splat looks empty or untrained")
    center = solid.median(dim=0).values
    distances = (solid - center).norm(dim=1)
    return Framing(center=center, radius=float(torch.quantile(distances, FRAMING["radius_quantile"])))


def floater_keep(splat: Splat, framing: Framing) -> torch.Tensor:
    """(N,) bool: the Gaussians that are rendered (near enough to the framing centre)."""
    return (splat.means - framing.center).norm(dim=1) <= framing.radius * FRAMING["crop_factor"]


def crop_floaters(splat: Splat, framing: Framing) -> Splat:
    return splat.subset(floater_keep(splat, framing))


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
        "depth": z[order], "index": torch.nonzero(in_front).squeeze(1)[order],  # index into `splat`
    }


@dataclass(frozen=True)
class TileWeights:
    """Where each Gaussian's blending weight (alpha x transmittance in front of it) went over one tile."""

    seen: torch.Tensor  # (n,) summed over the tile's pixels: how many pixels' worth of the Gaussian shows
    hit: torch.Tensor  # (masks, n) the same, with each pixel weighted by each mask
    depth: torch.Tensor  # (pixels,) blending-weighted camera depth (divide by alpha for the surface depth)
    alpha: torch.Tensor  # (pixels,) coverage


def _composite_tile(g: dict[str, torch.Tensor], px: torch.Tensor, py: torch.Tensor, background: torch.Tensor,
                    masks: torch.Tensor | None = None) -> tuple[torch.Tensor, TileWeights | None]:
    """Front-to-back alpha compositing of depth-sorted Gaussians over one tile's pixels. With masks (pixels,
    masks) of 0..1 pixel weights, also returns where each Gaussian's weight went (TileWeights)."""
    color = torch.zeros(len(px), 3, device=px.device)
    trans = torch.ones(len(px), device=px.device)
    if masks is not None:
        depth = torch.zeros(len(px), device=px.device)
        seen = torch.zeros(len(g["u"]), device=px.device)
        hit = torch.zeros(masks.shape[1], len(g["u"]), device=px.device)
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
        if masks is not None:
            depth += weights @ g["depth"][sl]
            seen[sl] = weights.sum(0)
            hit[:, sl] = masks.T @ weights
        trans = trans * one_minus.prod(1)
        if float(trans.max()) < RASTER["stop_transmittance"]:
            break
    color = color + trans[:, None] * background
    if masks is None:
        return color, None
    return color, TileWeights(seen=seen, hit=hit, depth=depth, alpha=1.0 - trans)


def _rasterize(g: dict[str, torch.Tensor], size: int, background: torch.Tensor,
               masks: torch.Tensor | None = None) -> tuple[torch.Tensor, dict[str, torch.Tensor] | None]:
    """Composites every tile. Returns the (size, size, 3) float image and, with masks (masks, size, size) of 0..1
    pixel weights, per projected Gaussian `seen` (n,) and `hit` (masks, n), plus `alpha` and `depth` maps."""
    tile = RASTER["tile_px"]
    if size % tile:
        raise SplatError(f"render size {size} must be a multiple of the {tile} px tile")
    device = g["u"].device
    tiles = size // tile
    image = background.expand(size, size, 3).clone()
    if masks is not None:
        n = len(g["u"])
        acc = {"seen": torch.zeros(n, device=device), "hit": torch.zeros(len(masks), n, device=device),
               "alpha": torch.zeros(size, size, device=device), "depth": torch.zeros(size, size, device=device)}
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
            rows, cols = slice(j * tile, (j + 1) * tile), slice(i * tile, (i + 1) * tile)
            gy, gx = torch.meshgrid(j * tile + offsets, i * tile + offsets, indexing="ij")
            tile_g = {k: v[idx] for k, v in g.items()}
            tile_masks = None if masks is None else masks[:, rows, cols].reshape(len(masks), tile * tile).T
            pixels, w = _composite_tile(tile_g, gx.reshape(-1), gy.reshape(-1), background, tile_masks)
            image[rows, cols] = pixels.reshape(tile, tile, 3)
            if w is not None:
                acc["seen"].index_add_(0, idx, w.seen)
                acc["hit"].index_add_(1, idx, w.hit)
                acc["alpha"][rows, cols] = w.alpha.reshape(tile, tile)
                acc["depth"][rows, cols] = w.depth.reshape(tile, tile)
    return image, (acc if masks is not None else None)


def _to_uint8(image: torch.Tensor) -> np.ndarray:
    return (image.clamp(0, 1) * 255 + 0.5).to(torch.uint8).cpu().numpy()


def render(splat: Splat, camera: Camera, size: int, background_rgb: tuple[int, int, int]) -> np.ndarray:
    """Renders one square view. Returns an (size, size, 3) uint8 RGB image."""
    g = _project(splat, camera, size)
    background = torch.tensor(background_rgb, device=g["u"].device, dtype=torch.float32) / 255
    image, _ = _rasterize(g, size, background)
    return _to_uint8(image)


# --- whole job --------------------------------------------------------------------------------


def _png_bytes(pixels: np.ndarray) -> bytes:
    buf = io.BytesIO()
    PILImage.fromarray(pixels).save(buf, format="PNG")
    return buf.getvalue()


def render_pngs(data: bytes, up_axis: str, angles: list[tuple[float, float]], size: int,
                background_rgb: tuple[int, int, int]) -> list[bytes]:
    """Renders one PNG per (azimuth_deg, elevation_deg) of a .spz or .ply, framed on the splat's solid part with
    floaters cropped."""
    splat = parse_splat(data, default_device())
    framing = robust_framing(splat)
    splat = crop_floaters(splat, framing)
    return [
        _png_bytes(render(splat, orbit_camera(framing, up_axis, azimuth, elevation), size, background_rgb))
        for azimuth, elevation in angles
    ]


# --- lifting 2D masks onto Gaussians ----------------------------------------------------------


def _surface_gap(g: dict[str, torch.Tensor], alpha: torch.Tensor, depth: torch.Tensor, size: int) -> torch.Tensor:
    """(n,) each projected Gaussian's depth minus the rendered surface depth at its centre pixel; inf where the
    centre is off-screen or that pixel has too little coverage to have a surface."""
    px, py = g["u"].floor().long(), g["v"].floor().long()
    on = (px >= 0) & (px < size) & (py >= 0) & (py < size)
    gap = torch.full_like(g["depth"], math.inf)
    coverage = alpha[py[on], px[on]]
    surface = depth[py[on], px[on]] / coverage.clamp_min(1e-6)
    gap[on] = torch.where(coverage >= LIFT["surface_alpha"], g["depth"][on] - surface,
                          torch.full_like(coverage, math.inf))
    return gap


def lift_masks(data: bytes, up_axis: str, angles: list[tuple[float, float]], masks: list[tuple[int, np.ndarray]],
               size: int, background_rgb: tuple[int, int, int]) -> dict:
    """Lifts 2D masks drawn on views onto the Gaussians that show through them. Views are framed and cropped exactly
    as render_pngs renders them (the same cameras at any `size`), so masks drawn on its output line up.

    masks: one (index into `angles`, (size, size) uint8 pixel weight 0..255) per mask.
    Returns plain numpy for the candidate Gaussians only (some mask weight on them), C of them:
      ids (C,)           their indices in the file, as parse_splat reads it
      seen (V, C)        blending weight summed over pixels: how many pixels' worth of each shows in each view
      hit (M, C)         the same, with every pixel weighted by the mask
      depth_gap (V, C)   depth behind the rendered surface at the Gaussian's centre, in framing radii (inf when
                         off-screen or over no surface); Gaussians hidden behind the surface have a large gap
      item_px (V,)       the item's area in each view, in pixels (summed coverage)
      mask_item_px (M,)  the item's area inside each mask
    plus gaussians (count in the file), rendered (after the floater crop) and images (one PNG per view).
    """
    device = default_device()
    splat = parse_splat(data, device)
    total = len(splat.means)
    framing = robust_framing(splat)
    keep = floater_keep(splat, framing)
    file_ids = torch.nonzero(keep).squeeze(1)
    splat = splat.subset(keep)
    n, n_views, n_masks = len(splat.means), len(angles), len(masks)
    for view, mask in masks:
        if not 0 <= view < n_views or np.shape(mask) != (size, size):
            raise SplatError(f"each mask needs a view index below {n_views} and shape ({size}, {size})")

    background = torch.tensor(background_rgb, device=device, dtype=torch.float32) / 255
    seen = torch.zeros(n_views, n, device=device)
    hit = torch.zeros(n_masks, n, device=device)
    gap = torch.full((n_views, n), math.inf, device=device)
    item_px = torch.zeros(n_views, device=device)
    mask_item_px = torch.zeros(n_masks, device=device)
    images = []
    for v, (azimuth, elevation) in enumerate(angles):
        rows = [k for k, (view, _) in enumerate(masks) if view == v]
        view_masks = torch.zeros(len(rows), size, size, device=device)
        for r, k in enumerate(rows):
            view_masks[r] = torch.as_tensor(np.asarray(masks[k][1]), dtype=torch.float32, device=device) / 255
        g = _project(splat, orbit_camera(framing, up_axis, azimuth, elevation), size)
        image, w = _rasterize(g, size, background, view_masks)
        images.append(_png_bytes(_to_uint8(image)))
        idx = g["index"]
        seen[v, idx] = w["seen"]
        if rows:
            hit[torch.tensor(rows, device=device)[:, None], idx[None, :]] = w["hit"]
            mask_item_px[rows] = (view_masks * w["alpha"]).sum((1, 2))
        item_px[v] = w["alpha"].sum()
        gap[v, idx] = _surface_gap(g, w["alpha"], w["depth"], size) / framing.radius

    c = torch.nonzero((hit > LIFT["min_hit_px"]).any(0)).squeeze(1)
    return {
        "gaussians": total,
        "rendered": n,
        "ids": file_ids[c].cpu().numpy().astype(np.int64),
        "seen": seen[:, c].cpu().numpy(),
        "hit": hit[:, c].cpu().numpy(),
        "depth_gap": gap[:, c].cpu().numpy(),
        "item_px": item_px.cpu().numpy(),
        "mask_item_px": mask_item_px.cpu().numpy(),
        "images": images,
    }


# --- tinting a copy of the file ---------------------------------------------------------------


def _checked_ids(ids: np.ndarray, count: int) -> np.ndarray:
    ids = np.unique(np.asarray(ids, dtype=np.int64))
    if ids.size and (ids[0] < 0 or ids[-1] >= count):
        raise SplatError(f"Gaussian indices must lie in 0..{count - 1}")
    return ids


def _blend(colour: np.ndarray, rgb: tuple[float, float, float], strength: float) -> np.ndarray:
    return (1.0 - strength) * np.clip(colour, 0.0, 1.0) + strength * np.asarray(rgb, dtype=np.float32)


def tint_splat(data: bytes, ids: np.ndarray, rgb: tuple[float, float, float], strength: float) -> bytes:
    """A copy of a .spz or .ply (same format) with the Gaussians `ids` (file order, as parse_splat reads it) blended
    toward `rgb` (0..1) by `strength` (0..1), and their higher SH bands zeroed so the tint looks the same from every
    side. All other Gaussians and fields keep their exact bytes (an .spz is re-compressed)."""
    if data[:2] == b"\x1f\x8b":
        return _tint_spz(data, ids, rgb, strength)
    return _tint_ply(data, ids, rgb, strength)


def _tint_ply(data: bytes, ids: np.ndarray, rgb: tuple[float, float, float], strength: float) -> bytes:
    count, names, offset = _read_header(data)
    ids = _checked_ids(ids, count)
    dtype = np.dtype([(n, "<f4") for n in names])
    rows = np.frombuffer(data, dtype=dtype, count=count, offset=offset).copy()
    dc = np.stack([rows[f"f_dc_{c}"][ids] for c in range(3)], axis=1)
    target = _blend(0.5 + SH_C0 * dc, rgb, strength)
    for c in range(3):
        rows[f"f_dc_{c}"][ids] = (target[:, c] - 0.5) / SH_C0
    for name in names:
        if name.startswith("f_rest_"):
            rows[name][ids] = 0.0
    end = offset + count * dtype.itemsize
    return data[:offset] + rows.tobytes() + data[end:]


def _tint_spz(data: bytes, ids: np.ndarray, rgb: tuple[float, float, float], strength: float) -> bytes:
    raw = bytearray(_spz_payload(data))
    _, n, _, layout = _spz_layout(raw)
    ids = _checked_ids(ids, n)
    offset, size = layout["colors"]
    colors = np.frombuffer(raw, np.uint8, n * size, offset).reshape(n, size)  # writes go into `raw`
    dc = (colors[ids].astype(np.float32) / 255.0 - 0.5) / SPZ["color_scale"]
    target = _blend(0.5 + SH_C0 * dc, rgb, strength)
    encoded = ((target - 0.5) / SH_C0 * SPZ["color_scale"] + 0.5) * 255.0
    colors[ids] = np.clip(np.round(encoded), 0, 255).astype(np.uint8)
    offset, size = layout["sh"]
    if size:
        np.frombuffer(raw, np.uint8, n * size, offset).reshape(n, size)[ids] = SPZ["sh_zero_byte"]
    return gzip.compress(bytes(raw), mtime=0)
