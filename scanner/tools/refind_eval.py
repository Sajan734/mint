#!/usr/bin/env python3
"""Can the scanner re-find the item after a hand turn? Measured on a real walk-around scan.

Relative to the item, walking around a still item is the same as turning the item in front of a
still camera, and ARKit's poses are the ground truth. So: build the item's 3D feature map from one
stretch of the lap (known poses), then re-find the camera from frames further round the lap using
only that map (SIFT + PnP-RANSAC), and compare with ARKit.

  python refind_eval.py scan.zip [--map-arc 90] [--step 5]

Reports, per angular gap between the query view and the map: success rate, rotation and
translation error. Only item features count: features must lie inside the projected item box, and
map points must triangulate inside the item's 3D box above the table (the background moves when
the item is really turned, so it must not help).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np

ARKIT_TO_CV = np.diag([1.0, -1.0, -1.0, 1.0])


def load(path: Path):
    tmp = Path(tempfile.mkdtemp(prefix="mint-refind-"))
    with zipfile.ZipFile(path) as z:
        z.extractall(tmp)
    root = next(tmp.rglob("poses.jsonl")).parent
    poses = [json.loads(l) for l in (root / "poses.jsonl").read_text().splitlines() if l.strip()]
    cap = json.loads((root / "capture.json").read_text())
    frames, vc = [], cv2.VideoCapture(str(root / "video.mp4"))
    while True:
        ok, f = vc.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
    return poses, cap, frames


def world_to_cam(pose_rowmajor):
    """Raw ARKit camera-to-world → OpenCV world-to-camera (R, t)."""
    c2w = np.asarray(pose_rowmajor, float) @ ARKIT_TO_CV
    w2c = np.linalg.inv(c2w)
    return w2c[:3, :3], w2c[:3, 3]


def item_box(cap, pad=0.01):
    it = cap["item"]
    c = np.asarray(it["footprint_centre"], float)
    w, h, d = it["size_m"]
    r = 0.5 * max(w, d) + pad  # axis-aligned square footprint around the centre (heading unknown)
    lo = np.array([c[0] - r, it["plane_y"] + 0.003, c[2] - r])
    hi = np.array([c[0] + r, it["plane_y"] + h + pad, c[2] + r])
    return lo, hi


def roi_mask(lo, hi, R, t, K, shape, dilate=12):
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    pc = (R @ corners.T).T + t
    if np.any(pc[:, 2] <= 0.01):
        return None
    uv = (K @ pc.T).T
    uv = (uv[:, :2] / uv[:, 2:]).astype(np.int32)
    m = np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(m, cv2.convexHull(uv), 255)
    return cv2.dilate(m, np.ones((dilate, dilate), np.uint8))


def azimuth(pose, centre):
    p = np.asarray(pose, float)[:3, 3] - centre
    return np.degrees(np.arctan2(p[0], p[2])) % 360


def rot_err_deg(Ra, Rb):
    c = (np.trace(Ra.T @ Rb) - 1) / 2
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scan", type=Path)
    ap.add_argument("--map-arc", type=float, default=90, help="degrees of the lap used to build the map")
    ap.add_argument("--step", type=int, default=5, help="use every Nth frame as a keyframe/query")
    args = ap.parse_args()

    poses, cap, frames = load(args.scan)
    lo, hi = item_box(cap)
    centre = np.asarray(cap["item"]["centre"], float)
    sift = cv2.SIFT_create(nfeatures=1500, contrastThreshold=0.02)
    matcher = cv2.BFMatcher(cv2.NORM_L2)

    az = np.array([azimuth(p["pose_world"], centre) for p in poses])
    az_unwrapped = np.degrees(np.unwrap(np.radians(az)))
    travelled = np.abs(az_unwrapped - az_unwrapped[0])

    # Keyframes: every Nth frame, with its pose and features inside the projected item box.
    kf = {}
    for i in range(0, len(poses), args.step):
        p = poses[i]
        if p.get("tracking") != "normal":
            continue
        K = np.asarray(p["intrinsics"], float)
        R, t = world_to_cam(p["pose_world"])
        m = roi_mask(lo, hi, R, t, K, frames[i].shape)
        if m is None:
            continue
        kps, des = sift.detectAndCompute(frames[i], m)
        if des is None or len(kps) < 8:
            continue
        kf[i] = dict(K=K, R=R, t=t, kps=kps, des=des, travelled=travelled[i])
    ids = sorted(kf)
    if not ids:
        print("no keyframes with item features")
        return 1
    print(f"{len(poses)} frames, {len(ids)} keyframes with item features; "
          f"median features/keyframe {int(np.median([len(kf[i]['kps']) for i in ids]))}; lap covers {travelled.max():.0f}°")

    # Map: triangulate matches between keyframe pairs inside the first `map_arc` degrees.
    map_ids = [i for i in ids if kf[i]["travelled"] <= args.map_arc]
    pts3d, descs = [], []
    for a_idx, a in enumerate(map_ids):
        for b in map_ids[a_idx + 1:]:
            base = abs(kf[b]["travelled"] - kf[a]["travelled"])
            if not 6 <= base <= 30:
                continue
            A, B = kf[a], kf[b]
            pairs = [m for m, n in (x for x in matcher.knnMatch(A["des"], B["des"], k=2) if len(x) == 2)
                     if m.distance < 0.75 * n.distance]
            if len(pairs) < 8:
                continue
            ua = np.float32([A["kps"][m.queryIdx].pt for m in pairs]).T
            ub = np.float32([B["kps"][m.trainIdx].pt for m in pairs]).T
            Pa = A["K"] @ np.hstack([A["R"], A["t"][:, None]])
            Pb = B["K"] @ np.hstack([B["R"], B["t"][:, None]])
            X = cv2.triangulatePoints(Pa, Pb, ua, ub)
            X = (X[:3] / X[3]).T
            for j, x in enumerate(X):
                if np.any(x < lo) or np.any(x > hi):
                    continue  # not on the item (table, background)
                ok = True
                for F, u in ((A, ua[:, j]), (B, ub[:, j])):
                    pc = F["R"] @ x + F["t"]
                    if pc[2] <= 0:
                        ok = False
                        break
                    proj = (F["K"] @ pc)[:2] / pc[2]
                    if np.linalg.norm(proj - u) > 2.0:
                        ok = False
                        break
                if ok:
                    pts3d.append(x)
                    descs.append(A["des"][pairs[j].queryIdx])
    if len(pts3d) < 10:
        print(f"map: only {len(pts3d)} points on the item. Too few to re-find anything (too small/plain in frame).")
        return 1
    pts3d, descs = np.float32(pts3d), np.float32(descs)
    print(f"map: {len(pts3d)} 3D points on the item from {len(map_ids)} keyframes in the first {args.map_arc:.0f}°")

    def ratio_ok(m, n):
        # The same physical point is triangulated from several keyframe pairs, so the map holds
        # near-duplicate descriptors. If the two nearest are the same 3D point, it's not ambiguous.
        return m.distance < 0.8 * n.distance or np.linalg.norm(pts3d[m.trainIdx] - pts3d[n.trainIdx]) < 0.01

    # Queries: every keyframe. Gap = degrees past the edge of the map (≤ 0 = inside it: a control).
    rows = []
    for i in ids:
        gap = kf[i]["travelled"] - args.map_arc
        Q = kf[i]
        pairs = [m for m, n in (x for x in matcher.knnMatch(Q["des"], descs, k=2) if len(x) == 2) if ratio_ok(m, n)]
        ok, R_est, t_est, inl = False, None, None, 0
        if len(pairs) >= 6:
            obj = pts3d[[m.trainIdx for m in pairs]]
            img = np.float32([Q["kps"][m.queryIdx].pt for m in pairs])
            res, rvec, tvec, inliers = cv2.solvePnPRansac(obj, img, Q["K"], None, reprojectionError=3.0,
                                                          iterationsCount=500, flags=cv2.SOLVEPNP_EPNP)
            if res and inliers is not None and len(inliers) >= 8:
                rvec, tvec = cv2.solvePnPRefineLM(obj[inliers[:, 0]], img[inliers[:, 0]], Q["K"], None, rvec, tvec)
                R_est, t_est, inl, ok = cv2.Rodrigues(rvec)[0], tvec[:, 0], len(inliers), True
        if ok:
            c_est, c_gt = -R_est.T @ t_est, -Q["R"].T @ Q["t"]
            rows.append((gap, True, rot_err_deg(R_est, Q["R"]), 100 * np.linalg.norm(c_est - c_gt), inl, len(pairs)))
        else:
            rows.append((gap, False, None, None, inl, len(pairs)))

    print("\ngap past map   queries  re-found  rot err ° (median, max)  pos err cm (median, max)  inliers")
    for lo_g, hi_g in ((-360, 0), (0, 15), (15, 30), (30, 45), (45, 60), (60, 90), (90, 360)):
        sel = [r for r in rows if lo_g < r[0] <= hi_g]
        if not sel:
            continue
        good = [r for r in sel if r[1]]
        rot = [r[2] for r in good]
        pos = [r[3] for r in good]
        fmt = lambda v: f"{np.median(v):5.2f}, {np.max(v):5.2f}" if v else "   -  ,   -  "
        label = "inside map" if hi_g == 0 else f"{lo_g:3d}–{hi_g:<3d}°"
        print(f"{label:<11}        {len(sel):4d}     {len(good):4d}     {fmt(rot):>18}     {fmt(pos):>18}    "
              f"{int(np.median([r[4] for r in good])) if good else 0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
