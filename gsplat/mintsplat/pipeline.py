"""Stage driver. Each stage is timed; `stop_after` lets us iterate on one stage at a time."""
from pathlib import Path

import numpy as np

from . import debug, frames as frames_mod, masks as masks_mod, poses as poses_mod
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
    import cv2

    out["files"]["poses.jpg"] = cv2.imencode(".jpg", cv2.cvtColor(poses_mod.preview(
        c2w.cpu().numpy(), init_pts.cpu().numpy(), init_cols.cpu().numpy()), cv2.COLOR_RGB2BGR))[1].tobytes()
    if cfg["stop_after"] == "poses":
        out["timings"] = {**T.t, "total": T.total()}
        return out

    raise NotImplementedError("training lands in the next milestone")
