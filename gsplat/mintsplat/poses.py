"""Camera poses + an initial object point cloud from VGGT, then a gravity-aligned scan frame.

Conventions (match CLAUDE.md §6.2): OpenCV cameras (x right, y down, z forward),
world +Y up, origin on the support plane directly under the object.
"""
import cv2
import numpy as np
import torch


def run_vggt(model, frames: list[np.ndarray], long_side: int = 518):
    """Returns world-to-camera (N,3,4) and K (N,3,3) at full frame resolution, plus depth/conf at VGGT res."""
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    h, w = frames[0].shape[:2]
    if w >= h:
        W, H = long_side, round(long_side * h / w / 14) * 14
    else:
        H, W = long_side, round(long_side * w / h / 14) * 14
    small = [cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA) for f in frames]
    x = torch.from_numpy(np.stack(small)).permute(0, 3, 1, 2).float().div(255).cuda()[None]
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        out = model(x)
    ext, intr = pose_encoding_to_extri_intri(out["pose_enc"], (H, W))
    ext, K_small = ext[0].float(), intr[0].float()
    K = K_small.clone()
    K[:, 0] *= w / W
    K[:, 1] *= h / H
    return ext, K, K_small, out["depth"][0, ..., 0].float(), out["depth_conf"][0].float(), (W, H)


def unproject(depth, K_small, ext, sel):
    """World points for pixels where sel is True. depth (H,W), sel bool (H,W) tensor."""
    H, W = depth.shape
    ys, xs = torch.meshgrid(torch.arange(H, device=depth.device), torch.arange(W, device=depth.device), indexing="ij")
    pix = torch.stack([xs + 0.5, ys + 0.5, torch.ones_like(xs)], -1).float()
    xc = (pix @ torch.linalg.inv(K_small).T) * depth[..., None]
    R, t = ext[:, :3], ext[:, 3]
    return ((xc - t) @ R)[sel]  # R^T (x_cam - t)


UP = {
    "max_tilt_deg": 40.0,  # a support plane must be within this of the cameras' average "up"
    "min_inlier_frac": 0.08,  # below this the plane is not trusted; fall back to the camera up
    "plane_thresh": 0.02,  # RANSAC inlier distance, in object radii
    "bottom_quantile": 0.02,  # the object's lowest points (robust) rest on y = 0
}


def fit_plane(pts: np.ndarray, thresh: float, up_hint: np.ndarray, iters: int = 1024, seed: int = 0):
    """RANSAC plane restricted to roughly horizontal planes (normal within UP["max_tilt_deg"] of up_hint),
    all hypotheses scored at once on the GPU. Walls and the sides of a box under the object are rejected,
    which an unconstrained fit happily picks. Returns (unit normal, point, inlier fraction) or None."""
    g = torch.Generator(device="cuda").manual_seed(seed)
    P = torch.from_numpy(pts).float().cuda()
    up = torch.from_numpy(up_hint).float().cuda()
    tri = P[torch.randint(len(P), (iters, 3), device="cuda", generator=g)]
    n = torch.linalg.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n = n / n.norm(dim=1, keepdim=True).clamp_min(1e-12)
    d = ((P[None] - tri[:, :1]) * n[:, None]).sum(-1).abs()  # (iters, M)
    counts = (d < thresh).sum(1)
    flat = (n @ up).abs() >= np.cos(np.radians(UP["max_tilt_deg"]))
    counts = torch.where(flat, counts, torch.full_like(counts, -1))
    if int(counts.max()) <= 0:
        return None
    k = int(counts.argmax())
    best = d[k] < thresh
    p = P[best]
    ctr = p.mean(0)
    normal = torch.linalg.svd(p - ctr, full_matrices=False)[2][2]  # least-squares refit on inliers
    if (normal @ up).abs() < np.cos(np.radians(UP["max_tilt_deg"])):
        normal = n[k]  # the refit drifted onto a wall; keep the sampled horizontal normal
    return normal.cpu().numpy(), ctr.cpu().numpy(), float(best.float().mean())


def align_transform(up: np.ndarray, obj_pts: np.ndarray) -> np.ndarray:
    """4x4 world -> scan frame: +Y = up, X along the object's long axis on the ground, origin under the
    object with its lowest points (robustly) at y = 0.

    Aligning yaw to the object (instead of an arbitrary camera) makes orientation-based outputs (the
    8 reference views, "front" in renders) consistent across scans of different objects."""
    y = up / np.linalg.norm(up)
    flat = obj_pts - np.outer(obj_pts @ y, y)  # footprint on the ground plane
    ctr = flat.mean(0)
    _, _, vt = np.linalg.svd(flat - ctr, full_matrices=False)
    x = vt[0] - (vt[0] @ y) * y
    x /= np.linalg.norm(x)
    if (((flat - ctr) @ x) ** 3).mean() < 0:  # deterministic sign: the heavier tail points to +x
        x = -x
    z = np.cross(x, y)
    R = np.stack([x, y, z])  # rows; right-handed (x × y = z)
    origin = ctr + np.quantile(obj_pts @ y, UP["bottom_quantile"]) * y
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = -R @ origin
    return T


def estimate(model, frames: list[np.ndarray], masks: list[np.ndarray], n_init: int = 120_000):
    """Everything downstream needs: aligned c2w (N,4,4), K (N,3,3) full-res, init points + colours."""
    import time

    dev = "cuda"
    t0 = time.perf_counter()
    ext, K, K_small, depth, conf, (W, H) = run_vggt(model, frames)
    torch.cuda.synchronize()
    t_vggt = time.perf_counter() - t0
    N = len(frames)

    obj_P, obj_C, bg_P = [], [], []
    for v in range(N):
        m = cv2.resize(masks[v].astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
        inner = torch.from_numpy(cv2.erode(m, np.ones((5, 5), np.uint8)).astype(bool)).to(dev)
        outer = torch.from_numpy(~cv2.dilate(m, np.ones((15, 15), np.uint8)).astype(bool)).to(dev)
        c = conf[v]
        good_o = inner & (c >= torch.quantile(c[inner], 0.3)) if inner.any() else inner
        good_b = outer & (c >= torch.quantile(c[outer], 0.5)) if outer.any() else outer
        obj_P.append(unproject(depth[v], K_small[v], ext[v], good_o))
        small = cv2.resize(frames[v], (W, H), interpolation=cv2.INTER_AREA)
        obj_C.append(torch.from_numpy(small).to(dev)[good_o].float() / 255)
        bg_P.append(unproject(depth[v], K_small[v], ext[v], good_b))
    obj_P, obj_C, bg_P = torch.cat(obj_P), torch.cat(obj_C), torch.cat(bg_P)

    obj_np = obj_P.cpu().numpy()
    obj_ctr = np.median(obj_np, 0)
    obj_r = float(np.quantile(np.linalg.norm(obj_np - obj_ctr, axis=1), 0.95))

    c2w = torch.linalg.inv(torch.cat([ext, torch.tensor([[[0, 0, 0, 1.0]]], device=dev).expand(N, 1, 4)], 1))
    c2w = c2w.cpu().numpy()

    # gravity: the support plane, constrained to be roughly horizontal w.r.t. how the phone was held
    # (cameras' average up, i.e. minus their y axis); the camera up alone if no such plane is found
    cam_up = -c2w[:, :3, 1].mean(0)
    cam_up /= np.linalg.norm(cam_up)
    bg = bg_P.cpu().numpy()
    bg = bg[np.linalg.norm(bg - obj_ctr, axis=1) < 3 * obj_r]
    bg = bg[np.random.default_rng(0).choice(len(bg), min(len(bg), 20_000), replace=False)]
    plane = fit_plane(bg, UP["plane_thresh"] * obj_r, cam_up) if len(bg) >= 100 else None
    if plane is not None and plane[2] >= UP["min_inlier_frac"]:
        up, inlier_frac, up_source = plane[0], plane[2], "support_plane"
        if up @ cam_up < 0:
            up = -up
    else:
        up, inlier_frac, up_source = cam_up, (plane[2] if plane else 0.0), "camera_up"
    tilt = float(np.degrees(np.arccos(np.clip(up @ cam_up, -1, 1))))
    T = align_transform(up, obj_np)

    c2w = T[None] @ c2w
    Rt = torch.from_numpy(T).float().to(dev)
    obj_P = obj_P @ Rt[:3, :3].T + Rt[:3, 3]

    sel = torch.randperm(len(obj_P), device=dev)[:n_init]
    stats = {"up_source": up_source, "plane_inlier_frac": round(float(inlier_frac), 3),
             "up_vs_camera_deg": round(tilt, 1), "object_radius": round(obj_r, 4),
             "init_points": int(len(sel)), "vggt_res": [W, H],
             "vggt_s": round(t_vggt, 2), "post_s": round(time.perf_counter() - t0 - t_vggt, 2)}
    return torch.from_numpy(c2w).float().to(dev), K.to(dev), obj_P[sel], obj_C[sel], stats


def preview(c2w: np.ndarray, pts: np.ndarray, cols: np.ndarray, size: int = 480) -> np.ndarray:
    """Top (XZ) and side (XY) orthographic views of the aligned cloud + camera centres. y=0 line in side view."""
    cams = c2w[:, :3, 3]
    allp = np.concatenate([pts, cams])
    s = (size * 0.45) / np.abs(allp).max()
    panels = []
    for a, b, flip in ((0, 2, False), (0, 1, True)):
        img = np.full((size, size, 3), 24, np.uint8)
        to_px = lambda p: (int(size / 2 + p[a] * s), int(size / 2 - p[b] * s) if flip else int(size / 2 + p[b] * s))
        if flip:
            cv2.line(img, (0, size // 2), (size, size // 2), (80, 80, 80), 1)
        for p, c in zip(pts[::7], cols[::7]):
            img[np.clip(to_px(p)[1], 0, size - 1), np.clip(to_px(p)[0], 0, size - 1)] = (c * 255).astype(np.uint8)
        for p in cams:
            cv2.circle(img, to_px(p), 3, (61, 220, 151), -1)
        cv2.putText(img, "top (x,z)" if not flip else "side (x,y) +Y up", (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        panels.append(img)
    return np.concatenate(panels, 1)
