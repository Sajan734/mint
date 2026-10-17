"""Stage driver. Each stage is timed; `stop_after` lets us iterate on one stage at a time.

One video -> one splat. Two videos (upright orbit, then the object flipped over) -> each is
reconstructed on its own, the second is registered into the first's scan frame, and a single
splat is trained on all views.
"""
import subprocess
import time
from pathlib import Path

import numpy as np
import torch

from . import debug, export as export_mod, frames as frames_mod, masks as masks_mod, merge as merge_mod
from . import poses as poses_mod, train as train_mod
from .timing import Timer

DEFAULTS = {
    "n_frames": 80,  # per video
    "box": None,  # [x0, y0, x1, y1] in pixels of the first picked frame; None = centre prompt
    "stop_after": None,  # "masks" | "poses" | "register" | None
    "debug": True,  # contact sheets, held-out eval, turntable (adds a few seconds after the timed path)
}


def capture(models, video: bytes, cfg: dict, T: Timer, tag: str, out: dict) -> dict | None:
    """frames -> masks -> poses for one video. Returns None if a stop_after point was hit."""
    path = f"/tmp/in_{tag}.mp4"
    Path(path).write_bytes(video)
    with T.stage(f"1_frames_{tag}"):
        frames, _ = frames_mod.pick_frames(path, cfg["n_frames"])
    h, w = frames[0].shape[:2]
    print(f"[{tag}] picked {len(frames)} frames at {w}x{h}", flush=True)

    with T.stage(f"2_masks_{tag}"):
        masks = models.segmenter(frames, cfg["box"])
        ok = masks_mod.sane(masks)
    print(f"[{tag}] usable masks: {sum(ok)}/{len(ok)}; median area {np.median([m.mean() for m in masks]):.3f}",
          flush=True)
    if cfg["debug"]:
        pick = np.linspace(0, len(frames) - 1, 12).astype(int)
        out["files"][f"masks_{tag}.jpg"] = debug.sheet([debug.overlay(frames[i], masks[i]) for i in pick])
    out.setdefault("frames_used", {})[tag] = int(sum(ok))
    if cfg["stop_after"] == "masks":
        return None

    frames = [f for f, k in zip(frames, ok) if k]
    masks = [m for m, k in zip(masks, ok) if k]
    with T.stage(f"3_poses_{tag}"):
        c2w, K, pts, cols, pstats = poses_mod.estimate(models.vggt, frames, masks)
    out.setdefault("poses", {})[tag] = pstats
    print(f"[{tag}] poses: {pstats}", flush=True)
    if cfg["debug"]:
        out["files"][f"poses_{tag}.jpg"] = _jpg(poses_mod.preview(c2w.cpu().numpy(), pts.cpu().numpy(),
                                                                   cols.cpu().numpy()))
    if cfg["stop_after"] == "poses":
        return None
    return {"frames": frames, "masks": masks, "c2w": c2w, "K": K, "pts": pts, "cols": cols, "stats": pstats}


def run(models, videos: bytes | list[bytes], cfg: dict) -> dict:
    cfg = {**DEFAULTS, **(cfg or {})}
    videos = [videos] if isinstance(videos, (bytes, bytearray)) else list(videos)
    T = Timer()
    out: dict = {"files": {}}

    caps = []
    for tag, v in zip(["top", "bottom"], videos):
        c = capture(models, v, cfg, T, tag, out)
        if c is None:
            out["timings"] = {**T.t, "total": T.total()}
            return out
        caps.append(c)

    cap = caps[0]
    tcfg = dict(cfg.get("train") or {})
    if len(caps) == 2:
        with T.stage("3b_register"):
            S, rstats = merge_mod.register(caps[0], caps[1])
            bottom = merge_mod.apply(S, caps[1])
        out["register"] = rstats
        print(f"register: {rstats}", flush=True)
        if cfg["debug"]:
            # bottom's points drawn on top's frames, and top's points on bottom's frames (green dots
            # must stay inside the object everywhere)
            Sinv = torch.linalg.inv(S)
            top_in_bottom = caps[0]["pts"] @ Sinv[:3, :3].T + Sinv[:3, 3]
            out["files"]["register.jpg"] = debug.sheet(
                merge_mod.overlay(caps[0], bottom["pts"]) + merge_mod.overlay(caps[1], top_in_bottom))
        n = len(caps[0]["frames"])
        n_init = len(caps[0]["pts"])
        sel = torch.randperm(2 * n_init, device="cuda")[:n_init]
        cap = {
            "frames": caps[0]["frames"] + bottom["frames"], "masks": caps[0]["masks"] + bottom["masks"],
            "c2w": torch.cat([caps[0]["c2w"], bottom["c2w"]]), "K": torch.cat([caps[0]["K"], bottom["K"]]),
            "pts": torch.cat([caps[0]["pts"], bottom["pts"]])[sel],
            "cols": torch.cat([caps[0]["cols"], bottom["cols"]])[sel], "stats": caps[0]["stats"],
        }
        tcfg.setdefault("session_split", n)  # first n views are the top capture
        if cfg["stop_after"] == "register":
            out["timings"] = {**T.t, "total": T.total()}
            return out

    with T.stage("4_train"):
        params, c2w_ref, views, train_ids, test_ids = train_mod.train(
            cap["c2w"], cap["K"], cap["frames"], cap["masks"], cap["pts"], cap["cols"], tcfg)

    with T.stage("5_clean_export"):
        keep, cstats = export_mod.keep_mask(params, c2w_ref, cap["K"], cap["masks"], cap["stats"]["object_radius"],
                                            cfg.get("export"))
        out["files"]["splat.ply"] = export_mod.to_ply(params, keep)
    out["gaussians"] = cstats
    print(f"cleanup: {cstats}", flush=True)

    out["timings"] = {**T.t, "total": T.total()}
    if not cfg["debug"]:
        return out

    # ---- evaluation + debug media (after the timed path)
    t0 = time.perf_counter()
    sh = {**train_mod.DEFAULTS, **tcfg}["sh_degree"]
    clean = {k: torch.nn.Parameter(v[keep]) for k, v in params.items()}
    out["eval_heldout_raw"], _ = train_mod.evaluate(params, cap["c2w"], views, test_ids, sh)  # before cleanup
    out["eval_heldout"], pairs = train_mod.evaluate(clean, cap["c2w"], views, test_ids, sh)
    out["eval_train"], _ = train_mod.evaluate(clean, c2w_ref, views, train_ids[::8], sh)
    print(f"held-out raw: {out['eval_heldout_raw']}  cleaned: {out['eval_heldout']}  train: {out['eval_train']}",
          flush=True)
    if pairs:
        pick = np.linspace(0, len(pairs) - 1, min(4, len(pairs))).astype(int)
        pairs = [pairs[i] for i in pick]
        out["files"]["heldout.jpg"] = debug.sheet([g for g, _ in pairs] + [r for _, r in pairs], cols=len(pairs))
    center = clean["means"].detach().median(0).values
    if len(caps) == 2:  # one loop above, one below
        tt = (train_mod.turntable(clean, c2w_ref, cap["K"], center, sh, n=60, elev_deg=30)
              + train_mod.turntable(clean, c2w_ref, cap["K"], center, sh, n=60, elev_deg=-30))
    else:
        tt = train_mod.turntable(clean, c2w_ref, cap["K"], center, sh)
    out["files"]["turntable.mp4"] = _mp4(tt)
    out["debug_extras_s"] = round(time.perf_counter() - t0, 2)
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
