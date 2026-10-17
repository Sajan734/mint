"""Stage driver. Each stage is timed; `stop_after` lets us iterate on one stage at a time."""
from pathlib import Path

import numpy as np

from . import debug, frames as frames_mod, masks as masks_mod
from .timing import Timer

DEFAULTS = {
    "n_frames": 80,
    "box": None,  # [x0, y0, x1, y1] in pixels of the first picked frame; None = centre prompt
    "stop_after": None,  # "masks" | None
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

    raise NotImplementedError("poses / training land in the next milestones")
