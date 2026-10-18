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
    "iters": 1000,  # optimizer steps; each step renders `batch` views
    "batch": 4,
    "cap_max": 200_000,
    "sh_degree": 3,
    "holdout_ids": (),  # views never trained on: the scan's held-out photos (heldout.py), evaluated in debug runs
    "crop_margin": 0.12,
    "edge_band_px": 2,
    "ssim_w": 0.2,
    "alpha_w": 0.1,
    "opacity_reg": 0.0005,  # higher values leave a see-through, blotchy surface (tested 0.01)
    "scale_reg": 0.01,
    "aniso_reg": 0.1,  # penalise needles: longest axis more than aniso_max x the middle one. Flat discs
    "aniso_max": 5.0,  # (surfaces) are untouched; needles grow along camera rays in barely-seen regions
    "pose_lr": 1e-4,
    "appearance_lr": 0.0,  # >0 enables per-view colour correction (slightly smoother, ~+4 s)
    "appearance_reg": 0.1,
    "session_reg": 0.05,
    "session_split": None,  # views >= this index come from a 2nd video: learn one gain/offset for them
    "pose_start": 100,
    "init_scale": 0.5,
    "train_scale": None,  # training resolution relative to the video frames; None = from train_px_budget
    "train_px_budget": 500_000,  # auto scale: the shared training crop gets at most this many pixels
}


def _ssim_window(device):
    g = torch.from_numpy(cv2.getGaussianKernel(11, 1.5)).float().to(device)
    return (g @ g.T)[None, None].expand(3, 1, 11, 11).contiguous()


def ssim_map(a, b, win):
    """a, b: (B,3,H,W) in [0,1] -> per-pixel SSIM (B,3,H,W). (A separable version with one
    concatenated 15-channel blur was tried and was slower: the concat costs more than it saves.)"""
    mu_a, mu_b = F.conv2d(a, win, padding=5, groups=3), F.conv2d(b, win, padding=5, groups=3)
    s_aa = F.conv2d(a * a, win, padding=5, groups=3) - mu_a ** 2
    s_bb = F.conv2d(b * b, win, padding=5, groups=3) - mu_b ** 2
    s_ab = F.conv2d(a * b, win, padding=5, groups=3) - mu_a * mu_b
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    return ((2 * mu_a * mu_b + c1) * (2 * s_ab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (s_aa + s_bb + c2))


def se3_exp(xi):
    """(N,6) twist [v, w] -> (N,4,4) rigid transform (Rodrigues rotation, translation = v).

    Closed form built with stack/cat: matrix_exp and in-place slice writes cost ~4 ms of CPU
    launch overhead per step, more than the rasteriser.
    """
    v, w = xi[:, :3], xi[:, 3:]
    th = w.norm(dim=1, keepdim=True).clamp_min(1e-8)[..., None]
    z = torch.zeros_like(w[:, 0])
    Kx = torch.stack([z, -w[:, 2], w[:, 1], w[:, 2], z, -w[:, 0], -w[:, 1], w[:, 0], z], 1).view(-1, 3, 3)
    R = torch.eye(3, device=xi.device) + torch.sin(th) / th * Kx + (1 - torch.cos(th)) / th ** 2 * (Kx @ Kx)
    bottom = torch.tensor([0.0, 0, 0, 1], device=xi.device).expand(len(xi), 1, 4)
    return torch.cat([torch.cat([R, v[..., None]], 2), bottom], 1)


def rigid_inv(T):
    """Inverse of a (4,4) rigid transform without a general solver."""
    Rt = T[:3, :3].T
    return torch.cat([torch.cat([Rt, -Rt @ T[:3, 3:]], 1), T[3:]], 0)


def _pad_to(a, h, w):
    """Zero-pad bottom/right so a downscaled frame still holds a full crop."""
    if a.shape[0] >= h and a.shape[1] >= w:
        return a
    out = np.zeros((max(h, a.shape[0]), max(w, a.shape[1])) + a.shape[2:], a.dtype)
    out[:a.shape[0], :a.shape[1]] = a
    return out


def auto_scale(masks, margin: float, budget_px: int) -> float:
    """Training scale so the shared crop (estimated as in prep_views) fits the pixel budget. Small or
    far objects train at full resolution, close-ups are downscaled instead of costing more per step."""
    boxes = []
    for m in masks:
        ys, xs = np.nonzero(m)
        boxes.append((xs.max() + 1 - xs.min(), ys.max() + 1 - ys.min()))
    bw, bh = np.array(boxes, float).T
    pad = 2 * margin * np.maximum(bw, bh)
    H, W = masks[0].shape
    area = min(W, np.percentile(bw + pad, 80)) * min(H, np.percentile(bh + pad, 80))
    return float(np.clip(np.sqrt(budget_px / area), 0.4, 1.0))


def prep_views(frames, masks, K, margin, band_px):
    """Crop every view around its mask with ONE shared crop size (so views batch in a single
    rasterisation call). Returns stacked GPU tensors + crop-adjusted K."""
    H, W = masks[0].shape
    boxes = []
    for m in masks:
        ys, xs = np.nonzero(m)
        boxes.append((xs.min(), xs.max() + 1, ys.min(), ys.max() + 1))
    bw = np.array([x1 - x0 for x0, x1, _, _ in boxes])
    bh = np.array([y1 - y0 for _, _, y0, y1 in boxes])
    pad = 2 * margin * np.maximum(bw, bh)
    # crop size from the 80th percentile view; the few larger (close-up) views are downscaled to fit
    cw = min(W, int(np.percentile(bw + pad, 80)) // 16 * 16 + 16)
    ch = min(H, int(np.percentile(bh + pad, 80)) // 16 * 16 + 16)
    kern = np.ones((2 * band_px + 1, 2 * band_px + 1), np.uint8)
    imgs, msk, wts, Ks = [], [], [], []
    for f, m, k, (x0, x1, y0, y1), p in zip(frames, masks, K, boxes, pad):
        s = min(1.0, cw / (x1 - x0 + p), ch / (y1 - y0 + p))
        k = k.clone()
        if s < 1.0:
            f = cv2.resize(f, (round(W * s), round(H * s)), interpolation=cv2.INTER_AREA)
            m = cv2.resize(m.astype(np.uint8), (round(W * s), round(H * s)), interpolation=cv2.INTER_NEAREST)
            k[:2] *= s
            x0, x1, y0, y1 = (int(c * s) for c in (x0, x1, y0, y1))
        fh, fw = m.shape
        cx0 = int(np.clip((x0 + x1) // 2 - cw // 2, 0, max(0, fw - cw)))
        cy0 = int(np.clip((y0 + y1) // 2 - ch // 2, 0, max(0, fh - ch)))
        valid = _pad_to(np.ones((fh, fw), np.uint8), cy0 + ch, cx0 + cw)  # 0 where padding was added
        f, m = _pad_to(f, cy0 + ch, cx0 + cw), _pad_to(m, cy0 + ch, cx0 + cw)
        mu8 = m.astype(np.uint8)
        band = cv2.dilate(mu8, kern) - cv2.erode(mu8, kern)
        imgs.append(f[cy0:cy0 + ch, cx0:cx0 + cw])
        msk.append(mu8[cy0:cy0 + ch, cx0:cx0 + cw])
        wts.append(((1 - band) * valid)[cy0:cy0 + ch, cx0:cx0 + cw])
        kc = k.clone()
        kc[0, 2] -= cx0
        kc[1, 2] -= cy0
        Ks.append(kc)
    return {"img": torch.from_numpy(np.stack(imgs)).cuda(), "mask": torch.from_numpy(np.stack(msk)).cuda().float(),
            "weight": torch.from_numpy(np.stack(wts)).cuda().float(), "K": torch.stack(Ks), "W": cw, "H": ch}


def render(params, viewmats, Ks, W, H, sh_degree, bgs):
    """viewmats (B,4,4), Ks (B,3,3), bgs (B,3) -> rgb (B,H,W,3), alpha (B,H,W), info."""
    from gsplat import rasterization

    colors = torch.cat([params["sh0"], params["shN"]], 1)
    rgb, alpha, info = rasterization(
        params["means"], params["quats"], torch.exp(params["scales"]), torch.sigmoid(params["opacities"]),
        colors, viewmats, Ks, W, H, sh_degree=sh_degree, backgrounds=bgs, packed=False)
    return rgb, alpha[..., 0], info


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


@torch.no_grad()
def contribution(params, c2w, views, ids, batch: int = 4) -> torch.Tensor:
    """Per Gaussian: total alpha-blending weight it receives over the given views, in pixels.

    Renders a constant white colour and reads d(sum of the image)/d(colour), which is exactly the sum of
    each Gaussian's blending weights. (The real colours would not do: the rasteriser clamps negative SH
    colours, which would make the darkest Gaussians of a black object look like they contribute nothing.)"""
    from gsplat import rasterization

    n = len(params["means"])
    ones = torch.ones(n, 3, device="cuda", requires_grad=True)
    means, quats = params["means"].detach(), params["quats"].detach()
    scales, opac = torch.exp(params["scales"].detach()), torch.sigmoid(params["opacities"].detach())
    total = torch.zeros(n, device="cuda")
    for i in range(0, len(ids), batch):
        v = torch.tensor(ids[i:i + batch], device="cuda")
        with torch.enable_grad():
            rgb, _, _ = rasterization(means, quats, scales, opac, ones, torch.linalg.inv(c2w[v]), views["K"][v],
                                      views["W"], views["H"], packed=False)
            rgb[..., 0].sum().backward()
        total += ones.grad[:, 0]
        ones.grad = None
    return total


def train(c2w, K, frames, masks, pts, cols, cfg: dict):
    from gsplat.strategy import MCMCStrategy

    torch.backends.cudnn.benchmark = True  # fixed crop/batch sizes: let cuDNN pick its fastest conv
    cfg = {**DEFAULTS, **(cfg or {})}
    iters, B = cfg["iters"], cfg["batch"]
    torch.manual_seed(0)
    test_ids = sorted(set(cfg["holdout_ids"]))
    train_ids = [i for i in range(len(frames)) if i not in test_ids]
    ts = cfg["train_scale"] or auto_scale(masks, cfg["crop_margin"], cfg["train_px_budget"])
    if ts != 1.0:
        h, w = masks[0].shape
        size = (round(w * ts), round(h * ts))
        frames = [cv2.resize(f, size, interpolation=cv2.INTER_AREA) for f in frames]
        masks = [cv2.resize(m.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool) for m in masks]
        K = K.clone()
        K[:, :2] *= ts
    views = prep_views(frames, masks, K, cfg["crop_margin"], cfg["edge_band_px"])
    W, H = views["W"], views["H"]
    print(f"  scale {ts:.2f}, crop {W}x{H}, {len(train_ids)} train / {len(test_ids)} held-out views, batch {B}",
          flush=True)

    scene_scale = 1.1 * float((c2w[:, :3, 3] - pts.mean(0)).norm(dim=1).max())
    params = init_params(pts, cols, cfg["init_scale"])
    lrs = {"means": 1.6e-4 * scene_scale, "scales": 5e-3, "quats": 1e-3, "opacities": 5e-2,
           "sh0": 2.5e-3, "shN": 2.5e-3 / 20}
    # batch scaling as in gsplat's simple_trainer
    optimizers = {k: torch.optim.Adam([{"params": params[k], "lr": lr * B ** 0.5, "name": k}], eps=1e-15 / B ** 0.5,
                                      betas=(1 - B * 0.1, 1 - B * 0.001), fused=True)
                  for k, lr in lrs.items()}
    means_sched = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], 0.01 ** (1 / iters))

    strategy = MCMCStrategy(cap_max=cfg["cap_max"], refine_start_iter=int(iters * 0.12),
                            refine_stop_iter=int(iters * 0.8), refine_every=max(10, iters // 40))
    strategy.check_sanity(params, optimizers)
    state = strategy.initialize_state()

    w2c = torch.linalg.inv(c2w)
    cam_delta = torch.nn.Parameter(torch.zeros(len(frames), 6, device="cuda"))
    # per-view colour correction (3x3 + bias): absorbs the phone's auto exposure / white balance
    # drifting around the orbit, which otherwise gets baked into the splat as blotches. Only used
    # while training; the exported splat keeps the neutral (shared) colours.
    app_A = torch.nn.Parameter(torch.eye(3, device="cuda").repeat(len(frames), 1, 1))
    app_b = torch.nn.Parameter(torch.zeros(len(frames), 3, device="cuda"))
    cam_opt = torch.optim.Adam([{"params": [cam_delta], "lr": cfg["pose_lr"] * B ** 0.5},
                                {"params": [app_A, app_b], "lr": cfg["appearance_lr"] * B ** 0.5}])
    use_app = cfg["appearance_lr"] > 0
    # 2nd video was lit differently (object flipped, phone re-exposed): one per-channel gain for all
    # of its views; the 1st video is the colour reference. Gain only, regularised and clamped:
    # surfaces only the 2nd video sees (the underside) can trade "darker gain, brighter splat"
    # freely, and a free offset drifted far enough to tint the underside brown.
    split = cfg["session_split"]
    sess_gain = torch.nn.Parameter(torch.zeros(3, device="cuda"))
    sess_opt = torch.optim.Adam([sess_gain], lr=1e-3 * B ** 0.5)
    zero_bg = torch.zeros(B, 3, device="cuda")

    win = _ssim_window("cuda")
    tid = torch.tensor(train_ids, device="cuda")
    sh_every = max(1, int(iters * 0.4) // max(1, cfg["sh_degree"]))
    prof = None
    for step in range(iters):
        if cfg.get("profile") and step in (300, 340):  # profile 40 steps mid-training
            if step == 300:
                prof = torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,
                                                          torch.profiler.ProfilerActivity.CUDA])
                prof.__enter__()
            else:
                torch.cuda.synchronize()
                prof.__exit__(None, None, None)
                print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=18), flush=True)
        v = tid[torch.randint(len(tid), (B,), device="cuda")]
        if step >= cfg["pose_start"]:
            viewmats = torch.stack([rigid_inv(T) for T in c2w[v] @ se3_exp(cam_delta[v])])
        else:
            viewmats = w2c[v]
        deg = min(cfg["sh_degree"], step // sh_every)
        bg = torch.rand(B, 3, device="cuda")
        rgb, alpha, info = render(params, viewmats, views["K"][v], W, H, deg, zero_bg)  # premultiplied
        a3 = alpha[..., None]
        if use_app:
            rgb = torch.einsum("bij,bhwj->bhwi", app_A[v], rgb) + app_b[v][:, None, None] * a3
        if split is not None:
            sb = (v >= split).float()[:, None, None, None]
            rgb = rgb * (1 + sb * sess_gain.clamp(-0.2, 0.25))
        rgb = rgb + bg[:, None, None] * (1 - a3)

        m, w = views["mask"][v][..., None], views["weight"][v][..., None]
        gt = views["img"][v].float() / 255 * m + bg[:, None, None] * (1 - m)
        wsum = w.sum() * 3
        l1 = ((rgb - gt).abs() * w).sum() / wsum
        s = ssim_map(rgb.permute(0, 3, 1, 2), gt.permute(0, 3, 1, 2), win).permute(0, 2, 3, 1)
        dssim = ((1 - s) * w).sum() / wsum
        a_loss = ((alpha[..., None] - m).abs() * w).sum() / w.sum()
        loss = ((1 - cfg["ssim_w"]) * l1 + cfg["ssim_w"] * dssim + cfg["alpha_w"] * a_loss
                + cfg["opacity_reg"] * torch.sigmoid(params["opacities"]).mean()
                + cfg["scale_reg"] * torch.exp(params["scales"]).mean())
        if cfg["aniso_reg"] > 0:
            ls = params["scales"].sort(dim=1).values  # log scales, ascending
            loss = loss + cfg["aniso_reg"] * F.relu(ls[:, 2] - ls[:, 1] - math.log(cfg["aniso_max"])).mean()
        if use_app:  # keep the corrections small so the splat's own colours stay the canonical ones
            loss = loss + cfg["appearance_reg"] * (((app_A[v] - torch.eye(3, device="cuda")) ** 2).mean()
                                                   + (app_b[v] ** 2).mean())
        if split is not None:
            loss = loss + cfg["session_reg"] * (sess_gain ** 2).mean()

        strategy.step_pre_backward(params, optimizers, state, step, info)
        loss.backward()
        for o in optimizers.values():
            o.step()
            o.zero_grad(set_to_none=True)
        if step >= cfg["pose_start"]:
            cam_opt.step()
        cam_opt.zero_grad(set_to_none=True)
        if split is not None:
            sess_opt.step()
            sess_opt.zero_grad(set_to_none=True)
        means_sched.step()
        strategy.step_post_backward(params, optimizers, state, step, info, lr=means_sched.get_last_lr()[0])
        if step % 200 == 0 or step == iters - 1:
            print(f"  step {step:5d} loss {loss.item():.4f} l1 {l1.item():.4f} n={len(params['means'])}", flush=True)

    with torch.no_grad():
        refined = c2w.clone()
        refined[train_ids] = c2w[train_ids] @ se3_exp(cam_delta[train_ids])
        if split is not None:
            print(f"  2nd-video colour gain {(1 + sess_gain.clamp(-0.2, 0.25)).tolist()}", flush=True)
    return params, refined, views, train_ids, test_ids


@torch.no_grad()
def evaluate(params, c2w, views, ids, sh_degree, pose_steps: int = 0):
    """PSNR / SSIM inside the object mask on held-out views (black bg). Returns metrics + (gt, render) pairs.

    pose_steps > 0 first fits each held-out camera's pose to the frozen splat (test-time pose alignment,
    the usual protocol when training refines poses: otherwise the metric punishes pose refinement)."""
    win = _ssim_window("cuda")
    psnrs, ssims, pairs = [], [], []
    bg = torch.zeros(3, device="cuda")
    frozen = {k: v.detach() for k, v in params.items()}
    W, H = views["W"], views["H"]
    for v in ids:
        K = views["K"][v]
        m = views["mask"][v][..., None]
        gt = views["img"][v].float() / 255 * m
        pose = c2w[v]
        if pose_steps:
            delta = torch.zeros(1, 6, device="cuda", requires_grad=True)
            opt = torch.optim.Adam([delta], lr=1e-3)
            with torch.enable_grad():
                for _ in range(pose_steps):
                    rgb, _, _ = render(frozen, rigid_inv(c2w[v] @ se3_exp(delta)[0])[None], K[None], W, H,
                                       sh_degree, bg[None])
                    loss = ((rgb[0] * m - gt).abs()).mean()
                    opt.zero_grad()
                    loss.backward()
                    opt.step()
            pose = c2w[v] @ se3_exp(delta.detach())[0]
        rgb, _, _ = render(frozen, rigid_inv(pose)[None], K[None], W, H, sh_degree, bg[None])
        r = rgb[0].clamp(0, 1) * m
        mse = ((r - gt) ** 2).sum() / (m.sum() * 3)
        psnrs.append(float(10 * torch.log10(1 / mse.clamp_min(1e-10))))
        s = ssim_map(r.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None], win)[0].permute(1, 2, 0)
        ssims.append(float((s * m).sum() / (m.sum() * 3)))
        pairs.append(((gt.cpu().numpy() * 255).astype(np.uint8), (r.cpu().numpy() * 255).astype(np.uint8)))
    return {"psnr_masked": round(float(np.mean(psnrs)), 2) if psnrs else None,
            "ssim_masked": round(float(np.mean(ssims)), 4) if ssims else None,
            "n_views": len(ids), "pose_fit_steps": pose_steps}, pairs


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
