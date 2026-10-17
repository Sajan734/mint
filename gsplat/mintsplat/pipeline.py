"""Stage driver. Each stage is timed; `stop_after` lets us iterate on one stage at a time."""
import subprocess
from pathlib import Path

import numpy as np
import torch

from . import debug, export as export_mod, frames as frames_mod, masks as masks_mod, poses as poses_mod
from . import train as train_mod
from .timing import Timer

DEFAULTS = {
    "n_frames": 80,
    "box": None,  # [x0, y0, x1, y1] in pixels of the first picked frame; None = centre prompt
    "stop_after": None,  # "masks" | "poses" | None
}


def run(models, video: bytes, cfg: dict) -> dict:
    cfg = {**DEFAULTS, **(cfg or {})}
    T = Timer()
    out: dict = {"files": {}}
    Path("/tmp/in.mp4").write_bytes(video)

    with T.stage("1_frames"):
        frames, src_idx = frames_mod.pick_frames("/tmp/in.mp4", cfg["n_frames"])
    h, w = frames[0].shape[:2]
    print(f"picked {len(frames)} frames at {w}x{h}", flush=True)

    with T.stage("2_masks"):
        masks = models.segmenter(frames, cfg["box"])
        ok = masks_mod.sane(masks)
    print(f"usable masks: {sum(ok)}/{len(ok)}; median area {np.median([m.mean() for m in masks]):.3f}", flush=True)

    pick = np.linspace(0, len(frames) - 1, 12).astype(int)
    out["files"]["masks.jpg"] = debug.sheet([debug.overlay(frames[i], masks[i]) for i in pick])
    out["frames_used"] = int(sum(ok))
    if cfg["stop_after"] == "masks":
        out["timings"] = {**T.t, "total": T.total()}
        return out

    frames = [f for f, k in zip(frames, ok) if k]
    masks = [m for m, k in zip(masks, ok) if k]

    with T.stage("3_poses"):
        c2w, K, init_pts, init_cols, pstats = poses_mod.estimate(models.vggt, frames, masks)
    out["poses"] = pstats
    print(f"poses: {pstats}", flush=True)
    out["files"]["poses.jpg"] = _jpg(poses_mod.preview(
        c2w.cpu().numpy(), init_pts.cpu().numpy(), init_cols.cpu().numpy()))
    if cfg["stop_after"] == "poses":
        out["timings"] = {**T.t, "total": T.total()}
        return out

    tcfg = cfg.get("train") or {}
    with T.stage("4_train"):
        params, c2w_ref, views, train_ids, test_ids = train_mod.train(c2w, K, frames, masks, init_pts, init_cols, tcfg)

    with T.stage("5_clean_export"):
        keep, cstats = export_mod.keep_mask(params, c2w_ref, K, masks, pstats["object_radius"], cfg.get("export"))
        out["files"]["splat.ply"] = export_mod.to_ply(params, keep)
    out["gaussians"] = cstats
    print(f"cleanup: {cstats}", flush=True)

    # ---- evaluation + debug media (not part of the timed path)
    sh = {**train_mod.DEFAULTS, **tcfg}["sh_degree"]
    clean = {k: torch.nn.Parameter(v[keep]) for k, v in params.items()}
    out["eval_heldout"], pairs = train_mod.evaluate(clean, c2w, views, test_ids, sh)
    out["eval_train"], _ = train_mod.evaluate(clean, c2w_ref, views, train_ids[::8], sh)
    print(f"held-out: {out['eval_heldout']}  train: {out['eval_train']}", flush=True)
    if pairs:
        pairs = pairs[:4]
        out["files"]["heldout.jpg"] = debug.sheet([g for g, _ in pairs] + [r for _, r in pairs], cols=len(pairs))
    center = clean["means"].detach().median(0).values
    out["files"]["turntable.mp4"] = _mp4(train_mod.turntable(clean, c2w_ref, K, center, sh))

    out["timings"] = {**T.t, "total": T.total()}
    return out


def _jpg(rgb) -> bytes:
    import cv2

    return cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def _mp4(frames, fps: int = 24) -> bytes:
    h, w = frames[0].shape[:2]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                    "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                    "/tmp/turntable.mp4"], input=np.stack(frames).tobytes(), check=True)
    return Path("/tmp/turntable.mp4").read_bytes()
