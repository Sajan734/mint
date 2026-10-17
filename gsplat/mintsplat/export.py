import io

import cv2
import numpy as np
import torch

DEFAULTS = {
    "min_opacity": 0.02,
    "vote_inside_frac": 0.85,  # keep a Gaussian if its centre lands inside the mask in >= this share of views
    "vote_min_views": 3,
    "vote_dilate_px": 4,
    "max_scale_frac": 0.2,  # of the object radius
}


@torch.no_grad()
def mask_votes(means, c2w, K, masks, dilate_px):
    """Per Gaussian: (#views where its centre projects in frame & in front, #those inside the mask)."""
    seen = torch.zeros(len(means), device="cuda")
    inside = torch.zeros(len(means), device="cuda")
    kern = np.ones((2 * dilate_px + 1, 2 * dilate_px + 1), np.uint8)
    for pose, k, m in zip(c2w, K, masks):
        H, W = m.shape
        w2c = torch.linalg.inv(pose)
        xc = means @ w2c[:3, :3].T + w2c[:3, 3]
        z = xc[:, 2]
        uv = (xc @ k.T)[:, :2] / z.clamp_min(1e-6)[:, None]
        u, v = uv[:, 0].long(), uv[:, 1].long()
        ok = (z > 0) & (u >= 0) & (u < W) & (v >= 0) & (v < H)
        md = torch.from_numpy(cv2.dilate(m.astype(np.uint8), kern)).cuda().bool()
        hit = torch.zeros_like(ok)
        hit[ok] = md[v[ok], u[ok]]
        seen += ok.float()
        inside += hit.float()
    return seen, inside


def keep_mask(params, c2w, K, masks, object_radius, cfg: dict):
    cfg = {**DEFAULTS, **(cfg or {})}
    seen, inside = mask_votes(params["means"], c2w, K, masks, cfg["vote_dilate_px"])
    vote_ok = (seen >= cfg["vote_min_views"]) & (inside >= cfg["vote_inside_frac"] * seen)
    op_ok = torch.sigmoid(params["opacities"]) >= cfg["min_opacity"]
    sc_ok = torch.exp(params["scales"]).max(1).values <= cfg["max_scale_frac"] * object_radius
    keep = vote_ok & op_ok & sc_ok
    stats = {"before": int(len(keep)), "after": int(keep.sum()),
             "dropped_vote": int((~vote_ok).sum()), "dropped_opacity": int((~op_ok).sum()),
             "dropped_scale": int((~sc_ok).sum())}
    return keep, stats


@torch.no_grad()
def to_ply(params, keep) -> bytes:
    """Standard 3DGS binary PLY (what Spark, SuperSplat and the INRIA viewers read)."""
    from plyfile import PlyData, PlyElement

    n = int(keep.sum())
    shN = params["shN"][keep].transpose(1, 2).reshape(n, -1)  # channel-major, as in INRIA's format
    q = params["quats"][keep]
    cols = {
        "xyz": params["means"][keep],
        "n": torch.zeros(n, 3, device=keep.device),
        "f_dc": params["sh0"][keep][:, 0, :],
        "f_rest": shN,
        "opacity": params["opacities"][keep][:, None],
        "scale": params["scales"][keep],
        "rot": q / q.norm(dim=1, keepdim=True),
    }
    names = (["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
             + [f"f_rest_{i}" for i in range(shN.shape[1])] + ["opacity"]
             + [f"scale_{i}" for i in range(3)] + [f"rot_{i}" for i in range(4)])
    data = torch.cat(list(cols.values()), 1).float().cpu().numpy()
    arr = np.zeros(n, dtype=[(k, "f4") for k in names])
    for i, k in enumerate(names):
        arr[k] = data[:, i]
    buf = io.BytesIO()
    PlyData([PlyElement.describe(arr, "vertex")], text=False).write(buf)
    return buf.getvalue()


def _cloud(params, keep, sh_degree: int):
    import spz

    n = int(keep.sum())
    q = params["quats"][keep]
    q = q / q.norm(dim=1, keepdim=True)
    n_sh = (sh_degree + 1) ** 2 - 1
    cloud = spz.GaussianCloud()
    cloud.sh_degree = sh_degree
    cloud.antialiased = False
    cloud.positions = params["means"][keep].float().cpu().numpy().reshape(-1)
    cloud.scales = params["scales"][keep].float().cpu().numpy().reshape(-1)
    cloud.rotations = q[:, [1, 2, 3, 0]].float().cpu().numpy().reshape(-1)  # gsplat wxyz -> spz xyzw
    cloud.alphas = params["opacities"][keep].float().cpu().numpy().reshape(-1)  # logits
    cloud.colors = params["sh0"][keep][:, 0, :].float().cpu().numpy().reshape(-1)  # SH DC, not RGB
    if n_sh:
        # spz wants coefficient-major, channel-inner: exactly gsplat's (N, n_sh, 3) layout
        cloud.sh = params["shN"][keep][:, :n_sh, :].float().cpu().numpy().reshape(-1)
    assert cloud.num_points == n
    return cloud


@torch.no_grad()
def to_spz(params, keep, sh_degree: int = 3, version: int = 3, sh1_bits: int = 6, sh_rest_bits: int = 5) -> bytes:
    """Niantic SPZ (quantised + compressed, ~10x smaller than PLY). Our scan frame is right-handed
    +Y up, i.e. SPZ's native RUB, so nothing is flipped. Version 3 (gzip) because viewers such as
    Spark 2.1 predate the v4 (zstd) container. SH bits 6/5 instead of the library's 5/4: measured
    on held-out views, 5/4 cost 0.76 dB PSNR for 2.4 MB, 6/5 costs 0.13 dB for 2.95 MB."""
    import spz

    opts = spz.PackOptions()
    opts.from_coord = spz.CoordinateSystem.RUB
    opts.version = version
    opts.sh1_bits, opts.sh_rest_bits = sh1_bits, sh_rest_bits
    return spz.save_spz_to_buffer(_cloud(params, keep, sh_degree), opts)


@torch.no_grad()
def from_spz(data: bytes) -> dict:
    """Decode an SPZ back into gsplat-style tensors (for checking what the viewer will get)."""
    import spz

    opts = spz.UnpackOptions()
    opts.to_coord = spz.CoordinateSystem.RUB
    c = spz.load_spz_from_buffer(data, opts)
    t = lambda a, *shape: torch.from_numpy(np.asarray(a, np.float32).copy()).cuda().view(*shape)
    n, n_sh = c.num_points, (c.sh_degree + 1) ** 2 - 1
    rot = t(c.rotations, n, 4)
    shN = torch.zeros(n, 15, 3, device="cuda")
    if n_sh:
        shN[:, :n_sh] = t(c.sh, n, n_sh, 3)
    return {"means": t(c.positions, n, 3), "scales": t(c.scales, n, 3), "quats": rot[:, [3, 0, 1, 2]],
            "opacities": t(c.alphas, n), "sh0": t(c.colors, n, 1, 3), "shN": shN}
