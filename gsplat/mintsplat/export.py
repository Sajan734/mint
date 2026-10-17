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
