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


def fit_plane(pts: np.ndarray, thresh: float, iters: int = 400, seed: int = 0):
    """RANSAC plane -> (unit normal, point on plane, inlier fraction)."""
    rng = np.random.default_rng(seed)
    best, best_n = None, -1
    for _ in range(iters):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < 1e-12:
            continue
        n /= np.linalg.norm(n)
        inl = np.abs((pts - a) @ n) < thresh
        if inl.sum() > best_n:
            best, best_n = inl, inl.sum()
    p = pts[best]
    ctr = p.mean(0)
    n = np.linalg.svd(p - ctr, full_matrices=False)[2][2]  # least-squares refit on inliers
    return n, ctr, best_n / len(pts)


def align_transform(n: np.ndarray, plane_pt: np.ndarray, obj_ctr: np.ndarray, cam_ctrs: np.ndarray,
                    cam0_right: np.ndarray) -> np.ndarray:
    """4x4 world -> scan frame: +Y = plane normal towards the cameras, origin under the object on the plane."""
    if (cam_ctrs.mean(0) - plane_pt) @ n < 0:
        n = -n
    y = n
    x = cam0_right - (cam0_right @ y) * y
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    R = np.stack([x, y, z])  # rows; right-handed (x × y = z)
    origin = obj_ctr - ((obj_ctr - plane_pt) @ y) * y
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = -R @ origin
    return T


def estimate(model, frames: list[np.ndarray], masks: list[np.ndarray], n_init: int = 120_000):
    """Everything downstream needs: aligned c2w (N,4,4), K (N,3,3) full-res, init points + colours."""
    dev = "cuda"
    ext, K, K_small, depth, conf, (W, H) = run_vggt(model, frames)
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

    # support plane from the background near the object (paper can curl further out)
    bg = bg_P.cpu().numpy()
    bg = bg[np.linalg.norm(bg - obj_ctr, axis=1) < 3 * obj_r]
    bg = bg[np.random.default_rng(0).choice(len(bg), min(len(bg), 50_000), replace=False)]
    n, plane_pt, inlier_frac = fit_plane(bg, thresh=0.02 * obj_r)

    c2w = torch.linalg.inv(torch.cat([ext, torch.tensor([[[0, 0, 0, 1.0]]], device=dev).expand(N, 1, 4)], 1))
    c2w = c2w.cpu().numpy()
    T = align_transform(n, plane_pt, obj_ctr, c2w[:, :3, 3], c2w[0, :3, 0])

    c2w = T[None] @ c2w
    Rt = torch.from_numpy(T).float().to(dev)
    obj_P = obj_P @ Rt[:3, :3].T + Rt[:3, 3]

    sel = torch.randperm(len(obj_P), device=dev)[:n_init]
    stats = {"plane_inlier_frac": round(float(inlier_frac), 3), "object_radius": round(obj_r, 4),
             "init_points": int(len(sel)), "vggt_res": [W, H]}
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
