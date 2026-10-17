"""Masked 3DGS training with gsplat's MCMC strategy (fixed Gaussian budget, relocation instead of
split/clone heuristics), L1 + SSIM, random backgrounds, alpha supervision and per-view pose refinement.

Each view is cropped to its mask's bounding box (+margin) so we don't spend rasterisation on
background pixels; the mask boundary band is ignored in the loss so paper colour can't bleed
into the object's silhouette.
"""
import math

import cv2
import numpy as np
import torch
import torch.nn.functional as F

C0 = 0.28209479177387814

DEFAULTS = {
    "iters": 4000,
    "cap_max": 300_000,
    "sh_degree": 3,
    "sh_every": 500,  # raise SH degree every N steps
    "holdout_every": 10,  # every Nth view is held out for evaluation (0 = none)
    "crop_margin": 0.12,
    "edge_band_px": 2,
    "ssim_w": 0.2,
    "alpha_w": 0.1,
    "opacity_reg": 0.01,
    "scale_reg": 0.01,
    "pose_lr": 1e-4,
    "pose_start": 300,
    "init_scale": 0.5,
}


def _ssim_window(device):
    g = torch.from_numpy(cv2.getGaussianKernel(11, 1.5)).float().to(device)
    return (g @ g.T)[None, None].expand(3, 1, 11, 11).contiguous()


def ssim_map(a, b, win):
    """a, b: (1,3,H,W) in [0,1] -> per-pixel SSIM (1,3,H,W)."""
    mu_a, mu_b = F.conv2d(a, win, padding=5, groups=3), F.conv2d(b, win, padding=5, groups=3)
    s_aa = F.conv2d(a * a, win, padding=5, groups=3) - mu_a ** 2
    s_bb = F.conv2d(b * b, win, padding=5, groups=3) - mu_b ** 2
    s_ab = F.conv2d(a * b, win, padding=5, groups=3) - mu_a * mu_b
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    return ((2 * mu_a * mu_b + c1) * (2 * s_ab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (s_aa + s_bb + c2))


def se3_exp(xi):
    """(N,6) twist [v, w] -> (N,4,4) rigid transform."""
    n = xi.shape[0]
    hat = torch.zeros(n, 4, 4, device=xi.device)
    v, w = xi[:, :3], xi[:, 3:]
    hat[:, 0, 1], hat[:, 0, 2], hat[:, 1, 2] = -w[:, 2], w[:, 1], -w[:, 0]
    hat[:, 1, 0], hat[:, 2, 0], hat[:, 2, 1] = w[:, 2], -w[:, 1], w[:, 0]
    hat[:, :3, 3] = v
    return torch.linalg.matrix_exp(hat)


def prep_views(frames, masks, K, margin, band_px):
    """Crop each view around its mask. Returns dicts of GPU tensors + crop-adjusted K."""
    views = []
    for f, m, k in zip(frames, masks, K):
        H, W = m.shape
        ys, xs = np.nonzero(m)
        x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        pad = int(margin * max(x1 - x0, y1 - y0))
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(W, x1 + pad), min(H, y1 + pad)
        mu8 = m.astype(np.uint8)
        kern = np.ones((2 * band_px + 1, 2 * band_px + 1), np.uint8)
        band = cv2.dilate(mu8, kern) - cv2.erode(mu8, kern)
        kc = k.clone()
        kc[0, 2] -= x0
        kc[1, 2] -= y0
        views.append({
            "img": torch.from_numpy(f[y0:y1, x0:x1]).cuda(),
            "mask": torch.from_numpy(mu8[y0:y1, x0:x1]).cuda().float(),
            "weight": torch.from_numpy(1 - band[y0:y1, x0:x1]).cuda().float(),
            "K": kc, "W": int(x1 - x0), "H": int(y1 - y0),
        })
    return views


def render(params, viewmat, K, W, H, sh_degree, bg):
    from gsplat import rasterization

    colors = torch.cat([params["sh0"], params["shN"]], 1)
    rgb, alpha, info = rasterization(
        params["means"], params["quats"], torch.exp(params["scales"]), torch.sigmoid(params["opacities"]),
        colors, viewmat[None], K[None], W, H, sh_degree=sh_degree, backgrounds=bg[None], packed=False)
    return rgb[0], alpha[0, ..., 0], info


def init_params(pts, cols, init_scale):
    from scipy.spatial import cKDTree

    p = pts.cpu().numpy()
    d, _ = cKDTree(p).query(p, k=4)
    dist = torch.from_numpy(np.clip(d[:, 1:].mean(1), 1e-7, None)).float().cuda()
    n = len(pts)
    return torch.nn.ParameterDict({
        "means": torch.nn.Parameter(pts.clone()),
        "scales": torch.nn.Parameter(torch.log(dist * init_scale)[:, None].repeat(1, 3)),
        "quats": torch.nn.Parameter(torch.tensor([1.0, 0, 0, 0], device="cuda").repeat(n, 1)),
        "opacities": torch.nn.Parameter(torch.logit(torch.full((n,), 0.5, device="cuda"))),
        "sh0": torch.nn.Parameter(((cols - 0.5) / C0)[:, None, :].clone()),
        "shN": torch.nn.Parameter(torch.zeros(n, 15, 3, device="cuda")),
    })


def split_views(n: int, every: int) -> tuple[list[int], list[int]]:
    test = [i for i in range(n) if every and i % every == every // 2]
    return [i for i in range(n) if i not in test], test


def train(c2w, K, frames, masks, pts, cols, cfg: dict):
    from gsplat.strategy import MCMCStrategy

    cfg = {**DEFAULTS, **(cfg or {})}
    iters = cfg["iters"]
    torch.manual_seed(0)
    train_ids, test_ids = split_views(len(frames), cfg["holdout_every"])
    views = prep_views(frames, masks, K, cfg["crop_margin"], cfg["edge_band_px"])

    scene_scale = 1.1 * float((c2w[:, :3, 3] - pts.mean(0)).norm(dim=1).max())
    params = init_params(pts, cols, cfg["init_scale"])
    lrs = {"means": 1.6e-4 * scene_scale, "scales": 5e-3, "quats": 1e-3, "opacities": 5e-2,
           "sh0": 2.5e-3, "shN": 2.5e-3 / 20}
    optimizers = {k: torch.optim.Adam([{"params": params[k], "lr": lr, "name": k}], eps=1e-15)
                  for k, lr in lrs.items()}
    means_sched = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], 0.01 ** (1 / iters))

    strategy = MCMCStrategy(cap_max=cfg["cap_max"], refine_start_iter=500,
                            refine_stop_iter=int(iters * 0.8), refine_every=100)
    strategy.check_sanity(params, optimizers)
    state = strategy.initialize_state()

    cam_delta = torch.nn.Parameter(torch.zeros(len(frames), 6, device="cuda"))
    cam_opt = torch.optim.Adam([cam_delta], lr=cfg["pose_lr"])

    win = _ssim_window("cuda")
    order = torch.randint(len(train_ids), (iters,)).tolist()
    for step in range(iters):
        v = train_ids[order[step]]
        view = views[v]
        pose = c2w[v] @ se3_exp(cam_delta[v:v + 1])[0] if step >= cfg["pose_start"] else c2w[v]
        deg = min(cfg["sh_degree"], step // cfg["sh_every"])
        bg = torch.rand(3, device="cuda")
        rgb, alpha, info = render(params, torch.linalg.inv(pose), view["K"], view["W"], view["H"], deg, bg)

        m, w = view["mask"], view["weight"]
        gt = view["img"].float() / 255 * m[..., None] + bg * (1 - m[..., None])
        wsum = w.sum() * 3
        l1 = ((rgb - gt).abs() * w[..., None]).sum() / wsum
        s = ssim_map(rgb.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None], win)[0].permute(1, 2, 0)
        dssim = ((1 - s) * w[..., None]).sum() / wsum
        a_loss = ((alpha - m).abs() * w).sum() / w.sum()
        loss = ((1 - cfg["ssim_w"]) * l1 + cfg["ssim_w"] * dssim + cfg["alpha_w"] * a_loss
                + cfg["opacity_reg"] * torch.sigmoid(params["opacities"]).mean()
                + cfg["scale_reg"] * torch.exp(params["scales"]).mean())

        strategy.step_pre_backward(params, optimizers, state, step, info)
        loss.backward()
        for o in optimizers.values():
            o.step()
            o.zero_grad(set_to_none=True)
        if step >= cfg["pose_start"]:
            cam_opt.step()
        cam_opt.zero_grad(set_to_none=True)
        means_sched.step()
        strategy.step_post_backward(params, optimizers, state, step, info, lr=means_sched.get_last_lr()[0])
        if step % 500 == 0 or step == iters - 1:
            print(f"  iter {step:5d} loss {loss.item():.4f} l1 {l1.item():.4f} n={len(params['means'])}", flush=True)

    with torch.no_grad():
        refined = c2w.clone()
        refined[train_ids] = c2w[train_ids] @ se3_exp(cam_delta[train_ids])
    return params, refined, views, train_ids, test_ids


@torch.no_grad()
def evaluate(params, c2w, views, ids, sh_degree):
    """PSNR / SSIM inside the object mask on held-out views (black bg). Returns metrics + (gt, render) pairs."""
    win = _ssim_window("cuda")
    psnrs, ssims, pairs = [], [], []
    bg = torch.zeros(3, device="cuda")
    for v in ids:
        view = views[v]
        rgb, _, _ = render(params, torch.linalg.inv(c2w[v]), view["K"], view["W"], view["H"], sh_degree, bg)
        m = view["mask"][..., None]
        gt = view["img"].float() / 255 * m
        r = rgb.clamp(0, 1) * m
        mse = ((r - gt) ** 2).sum() / (m.sum() * 3)
        psnrs.append(float(10 * torch.log10(1 / mse.clamp_min(1e-10))))
        s = ssim_map(r.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None], win)[0].permute(1, 2, 0)
        ssims.append(float((s * m).sum() / (m.sum() * 3)))
        pairs.append(((gt.cpu().numpy() * 255).astype(np.uint8), (r.cpu().numpy() * 255).astype(np.uint8)))
    return {"psnr_masked": round(float(np.mean(psnrs)), 2) if psnrs else None,
            "ssim_masked": round(float(np.mean(ssims)), 4) if ssims else None,
            "n_views": len(ids)}, pairs


def look_at(pos, target):
    """OpenCV c2w for a camera at pos looking at target, world +Y up."""
    f = target - pos
    f = f / f.norm()
    x = torch.linalg.cross(f, torch.tensor([0.0, 1.0, 0.0], device=pos.device))
    x = x / x.norm()
    y = torch.linalg.cross(f, x)
    m = torch.eye(4, device=pos.device)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, f, pos
    return m


@torch.no_grad()
def turntable(params, c2w, K, center, sh_degree, n=72, W=640, H=480, elev_deg=None):
    """Frames of a 360° orbit around +Y at the capture's mean distance (and elevation unless given)."""
    cams = c2w[:, :3, 3] - center
    dist = float(cams.norm(dim=1).mean())
    elev = math.radians(elev_deg) if elev_deg is not None else float(torch.asin(cams[:, 1] / cams.norm(dim=1)).mean())
    k = K[0].clone()
    s = W / (2 * float(k[0, 2]))
    k[:2] *= s
    k[0, 2], k[1, 2] = W / 2, H / 2
    bg = torch.full((3,), 0.07, device="cuda")
    out = []
    for i in range(n):
        az = 2 * math.pi * i / n
        pos = center + dist * torch.tensor([math.cos(elev) * math.cos(az), math.sin(elev),
                                            math.cos(elev) * math.sin(az)], device="cuda")
        rgb, _, _ = render(params, torch.linalg.inv(look_at(pos, center)), k, W, H, sh_degree, bg)
        out.append((rgb.clamp(0, 1).cpu().numpy() * 255).astype(np.uint8))
    return out
