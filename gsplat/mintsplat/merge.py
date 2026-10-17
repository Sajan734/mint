"""Register a second capture (object flipped over) into the first capture's scan frame.

Each capture is reconstructed and gravity-aligned on its own (object resting on y=0). The flipped
capture relates to the upright one by a similarity x_a = s*R*x_b + t with R = yaw * flip.

Signal: silhouette consistency in BOTH directions with NO trimming. Every point of capture b must
project inside the object mask in every view of capture a, and every point of a inside every mask
of b. One direction alone is minimised by shrinking the cloud; the pair balances scale. Our VGGT
clouds are clean (~0.2% of a cloud falls outside its own masks), so an untrimmed constraint is
affordable, and it's what makes the pose well determined: with even 10% slack, many wrong poses
score zero.

(Tried and dropped: a trimmed nearest-neighbour term between the clouds - it pulls the top shell
and the bottom plate into each other; joint VGGT on background-masked frames from both videos -
its cameras don't agree with the per-video ones.)
"""
import math

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from .train import se3_exp

FLIP = torch.diag(torch.tensor([1.0, -1.0, -1.0]))  # 180 deg about X: upside down


def _rot(rv):
    """(C,3) rotation vectors -> (C,3,3)."""
    return se3_exp(torch.cat([torch.zeros_like(rv), rv], 1))[:, :3, :3]


def _yaw(theta):
    c, s = torch.cos(theta), torch.sin(theta)
    o, z = torch.ones_like(theta), torch.zeros_like(theta)
    return torch.stack([c, z, s, z, o, z, -s, z, c], 1).view(-1, 3, 3)


class Silhouettes:
    """Distance-to-mask maps (0 inside the object) for a subset of one capture's views."""

    def __init__(self, c2w, K, masks, n_views: int = 32, scale: float = 0.25):
        idx = np.linspace(0, len(masks) - 1, min(n_views, len(masks))).astype(int)
        H, W = masks[0].shape
        maps = []
        for i in idx:
            small = cv2.resize(masks[i].astype(np.uint8), (round(W * scale), round(H * scale)),
                               interpolation=cv2.INTER_NEAREST)
            maps.append(cv2.distanceTransform(1 - small, cv2.DIST_L2, 3))
        self.d = torch.from_numpy(np.stack(maps)).float().cuda()[:, None]  # (V,1,h,w), pixels at `scale`
        self.w2c = torch.linalg.inv(c2w[idx])
        self.K = K[idx]
        self.W, self.H, self.scale = W, H, scale

    def penalty(self, pts: torch.Tensor, clamp: float = 30.0):
        """pts (C,N,3) per candidate -> (C,) mean distance outside the masks (px at map scale), untrimmed."""
        C, N, _ = pts.shape
        xc = torch.einsum("vij,cnj->vcni", self.w2c[:, :3, :3], pts) + self.w2c[:, None, None, :3, 3]
        z = xc[..., 2]
        uv = torch.einsum("vij,vcnj->vcni", self.K, xc)[..., :2] / z[..., None].clamp_min(1e-4)
        grid = torch.stack([uv[..., 0] / self.W * 2 - 1, uv[..., 1] / self.H * 2 - 1], -1)
        d = F.grid_sample(self.d, grid.view(len(self.d), C * N, 1, 2), align_corners=False,
                          padding_mode="border")[:, 0, :, 0].view(-1, C, N)
        d = torch.where(z > 0, d, torch.full_like(d, clamp)).clamp(max=clamp)
        return d.mean((0, 2))

    @torch.no_grad()
    def outside(self, pts: torch.Tensor):
        """pts (N,3) -> (fraction of projections outside the mask, mean distance outside in full-res px)."""
        xc = pts[None] @ self.w2c[:, :3, :3].transpose(1, 2) + self.w2c[:, None, :3, 3]
        z = xc[..., 2:3]
        uv = (xc @ self.K.transpose(1, 2))[..., :2] / z.clamp_min(1e-4)
        grid = torch.stack([uv[..., 0] / self.W * 2 - 1, uv[..., 1] / self.H * 2 - 1], -1)
        d = F.grid_sample(self.d, grid[:, :, None], align_corners=False, padding_mode="border")[:, 0, :, 0]
        d = torch.where(z[..., 0] > 0, d, torch.full_like(d, 1e3)) / self.scale
        return float((d > 2 / self.scale).float().mean()), float(d.clamp(max=200).mean())


def _sub(p, n, seed=0):
    g = torch.Generator(device=p.device).manual_seed(seed)
    return p[torch.randperm(len(p), device=p.device, generator=g)[:n]]


def _fit(R0, s0, t0, pa, pb, sil_a, sil_b, steps, lr, ha):
    """Optimise C candidate similarities (rotation delta, log scale, translation) from R0/s0/t0."""
    C = len(R0)
    rv = torch.zeros(C, 3, device="cuda", requires_grad=True)
    log_s = torch.log(s0).clone().requires_grad_(True)
    t = t0.clone().requires_grad_(True)
    opt = torch.optim.Adam([{"params": [rv, log_s], "lr": lr}, {"params": [t], "lr": lr * ha}])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, steps)

    def loss_fn():
        R, s = _rot(rv) @ R0, log_s.exp()
        b_in_a = s[:, None, None] * torch.einsum("cij,nj->cni", R, pb) + t[:, None]
        a_in_b = torch.einsum("cji,cnj->cni", R, pa[None] - t[:, None]) / s[:, None, None]
        return sil_a.penalty(b_in_a) + sil_b.penalty(a_in_b), R, s

    for _ in range(steps):
        loss, _, _ = loss_fn()
        opt.zero_grad()
        loss.sum().backward()
        opt.step()
        sched.step()
    with torch.no_grad():
        loss, R, s = loss_fn()
    return R.detach(), s.detach(), t.detach(), loss.detach()


def register(a: dict, b: dict, n_yaw: int = 24, coarse_steps: int = 200, fine_steps: int = 200):
    """4x4 similarity mapping capture b's scan frame into capture a's, plus health stats."""
    pa, pb = a["pts"], b["pts"]
    ha, hb = float(pa[:, 1].quantile(0.98)), float(pb[:, 1].quantile(0.98))
    s0 = ha / hb  # same object height above the support plane

    # coarse: every yaw in parallel, small clouds and view subsets
    thetas = torch.arange(n_yaw, device="cuda") * (2 * math.pi / n_yaw)
    R0 = _yaw(thetas) @ FLIP.cuda()
    pa_c, pb_c = _sub(pa, 1500), _sub(pb, 1500)
    pb_rot = torch.einsum("cij,nj->cni", R0, pb_c) * s0
    t0 = torch.zeros(n_yaw, 3, device="cuda")
    t0[:, [0, 2]] = pa_c[:, [0, 2]].median(0).values - pb_rot[..., [0, 2]].median(1).values
    t0[:, 1] = ha  # flipped: b's base (its y = h) lands on a's y = 0, b's y = 0 at a's top
    sil_a, sil_b = Silhouettes(a["c2w"], a["K"], a["masks"], 24), Silhouettes(b["c2w"], b["K"], b["masks"], 24)
    R, s, t, loss = _fit(R0, torch.full((n_yaw,), s0, device="cuda"), t0, pa_c, pb_c, sil_a, sil_b,
                         coarse_steps, 0.03, ha)
    order = loss.argsort()
    best = int(order[0])
    ang = torch.arccos(((torch.einsum("cij,ij->c", R, R[best]) - 1) / 2).clamp(-1, 1))
    distinct = loss[ang > math.radians(20)]
    print("  register coarse (start yaw: loss px):", ", ".join(
        f"{float(thetas[i]) * 180 / math.pi:.0f}: {float(loss[i]):.3f}" for i in order[:8].tolist()), flush=True)

    # fine: the winner, more points and views, lower learning rate
    sil_a, sil_b = Silhouettes(a["c2w"], a["K"], a["masks"], 64), Silhouettes(b["c2w"], b["K"], b["masks"], 64)
    R, s, t, loss_f = _fit(R[best:best + 1], s[best:best + 1], t[best:best + 1], _sub(pa, 5000, 1),
                           _sub(pb, 5000, 1), sil_a, sil_b, fine_steps, 0.005, ha)
    S = torch.eye(4, device="cuda")
    S[:3, :3] = s[0] * R[0]
    S[:3, 3] = t[0]
    stats = {"scale_b_to_a": round(float(s[0]), 4), "start_yaw_deg": round(float(thetas[best]) * 180 / math.pi),
             "coarse_loss_px": round(float(loss[best]), 4),
             "best_distinct_alternative_px": round(float(distinct.min()), 4) if len(distinct) else None,
             "fine_loss_px": round(float(loss_f[0]), 4),
             "up_dot": round(float(R[0][1, 1]), 3)}
    stats.update(check(S, a, b))
    return S, stats


def check(S, a: dict, b: dict) -> dict:
    """Silhouette consistency both ways (bottom pts in top masks, top pts in bottom masks)."""
    pb_in_a = b["pts"] @ S[:3, :3].T + S[:3, 3]
    Si = torch.linalg.inv(S)
    pa_in_b = a["pts"] @ Si[:3, :3].T + Si[:3, 3]
    fa, da = Silhouettes(a["c2w"], a["K"], a["masks"]).outside(pb_in_a[::20])
    fb, db = Silhouettes(b["c2w"], b["K"], b["masks"]).outside(pa_in_b[::20])
    self_f, _ = Silhouettes(a["c2w"], a["K"], a["masks"]).outside(a["pts"][::20])
    return {"outside_frac_bottom_in_top": round(fa, 3), "outside_frac_top_in_bottom": round(fb, 3),
            "outside_frac_top_in_top_baseline": round(self_f, 3),
            "outside_px_bottom_in_top": round(da, 1), "outside_px_top_in_bottom": round(db, 1)}


def apply(T: torch.Tensor, cap: dict) -> dict:
    """Move a capture's cameras and points by similarity T (scale goes into translations only)."""
    sR, t = T[:3, :3], T[:3, 3]
    s = torch.linalg.det(sR).abs() ** (1 / 3)
    R = sR / s
    c2w = cap["c2w"].clone()
    c2w[:, :3, :3] = R @ cap["c2w"][:, :3, :3]
    c2w[:, :3, 3] = cap["c2w"][:, :3, 3] @ sR.T + t
    return {**cap, "c2w": c2w, "pts": cap["pts"] @ sR.T + t}


@torch.no_grad()
def overlay(cap_into: dict, pts: torch.Tensor, n: int = 4) -> list[np.ndarray]:
    """Project points (already in cap_into's frame) onto a few of its frames, for eyeballing alignment."""
    out = []
    idx = np.linspace(0, len(cap_into["frames"]) - 1, n).astype(int)
    p = pts[torch.randperm(len(pts), device=pts.device)[:4000]]
    for i in idx:
        img = cap_into["frames"][i].copy()
        img[~cap_into["masks"][i]] = (img[~cap_into["masks"][i]] * 0.35).astype(np.uint8)
        w2c = torch.linalg.inv(cap_into["c2w"][i])
        xc = p @ w2c[:3, :3].T + w2c[:3, 3]
        uv = (xc @ cap_into["K"][i].T)[:, :2] / xc[:, 2:].clamp_min(1e-4)
        for u, v in uv.cpu().numpy().astype(int):
            if 0 <= u < img.shape[1] and 0 <= v < img.shape[0]:
                cv2.circle(img, (int(u), int(v)), 2, (61, 220, 151), -1)
        out.append(img)
    return out
