"""Stage driver. Each stage is timed; `stop_after` lets us iterate on one stage at a time.

One video -> one splat of the item's top half (coverage "top": the underside was never filmed, so viewers keep
the camera above it). Two videos (upright lap, then the item flipped over) -> each is reconstructed on its own,
the second is registered into the first's scan frame, and one splat is trained on all views (coverage "full").

Outputs (res["files"]): splat.spz, heldout/ (8 masked video frames + heldout.json, held out of training; see
heldout.py), spin/f00..f23.webp (the website's spin viewer). Debug runs add masks_*.jpg / poses_*.jpg /
register.jpg contact sheets and the held-out PSNR.
"""
import time

import numpy as np
import torch

from . import debug, export as export_mod, frames as frames_mod, heldout as heldout_mod, masks as masks_mod
from . import merge as merge_mod, poses as poses_mod, spin as spin_mod, train as train_mod
from .timing import Timer

DEFAULTS = {
    "n_frames": 80,  # per video
    "box": None,  # [x0, y0, x1, y1] in pixels of the first picked frame; None = centre prompt
    "box_refine": True,  # re-prompt SAM 2 with the first point mask's (grown) box to include attached parts
    "stop_after": None,  # "masks" | "poses" | "register" | None
    "debug": False,  # contact sheets + held-out PSNR (a few seconds after the timed path)
    "ply": False,  # also return the uncompressed .ply (~38 MB): only the buyer agent's comparison needs it
    "spin": True,  # the website's 24 spin frames
    "rotate_cw": None,  # per video, clockwise degrees to turn frames upright (the Mint app stores them sideways)
}


def decode_all(videos: list[bytes], n_frames: int, rotate_cw: list[int] | None = None):
    """Pick sharp frames from every video in parallel threads (OpenCV's decoder releases the GIL), turned upright
    by rotate_cw[i] clockwise degrees (the Mint app's frames are stored sideways). -> [(frames, frame indices)]."""
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    def one(i_v):
        i, v = i_v
        path = f"/tmp/in_{i}.mp4"
        Path(path).write_bytes(v)
        return frames_mod.pick_frames(path, n_frames, (rotate_cw or [0] * len(videos))[i])

    with ThreadPoolExecutor(len(videos)) as ex:
        return list(ex.map(one, enumerate(videos)))


def capture(models, frames: list[np.ndarray], video_frames: list[int], cfg: dict, T: Timer, tag: str,
            out: dict) -> dict | None:
    """masks -> poses for one video's frames. Returns None if a stop_after point was hit."""
    h, w = frames[0].shape[:2]
    print(f"[{tag}] picked {len(frames)} frames at {w}x{h}", flush=True)

    with T.stage(f"2_masks_{tag}"):
        masks = models.segmenter(frames, cfg["box"], cfg["box_refine"])
        ok = masks_mod.sane(masks)
    print(f"[{tag}] usable masks: {sum(ok)}/{len(ok)}; median area {np.median([m.mean() for m in masks]):.3f}",
          flush=True)
    if cfg["debug"]:
        pick = np.linspace(0, len(frames) - 1, 12).astype(int)
        out["files"][f"masks_{tag}.jpg"] = debug.sheet([debug.overlay(frames[i], masks[i]) for i in pick])
    out.setdefault("frames_used", {})[tag] = int(sum(ok))
    if cfg["stop_after"] == "masks":
        return None

    keep = [i for i, k in enumerate(ok) if k]
    frames, masks, video_frames = [frames[i] for i in keep], [masks[i] for i in keep], [video_frames[i] for i in keep]
    with T.stage(f"3_poses_{tag}"):
        c2w, K, pts, cols, pstats = poses_mod.estimate(models.vggt, frames, masks)
    out.setdefault("poses", {})[tag] = pstats
    print(f"[{tag}] poses: {pstats}", flush=True)
    if cfg["debug"]:
        out["files"][f"poses_{tag}.jpg"] = debug.jpg(poses_mod.preview(c2w.cpu().numpy(), pts.cpu().numpy(),
                                                                       cols.cpu().numpy()))
    if cfg["stop_after"] == "poses":
        return None
    return {"frames": frames, "masks": masks, "video_frames": video_frames, "c2w": c2w, "K": K, "pts": pts,
            "cols": cols, "stats": pstats}


def run(models, videos: bytes | list[bytes], cfg: dict, on_event=None) -> dict:
    """on_event(stage, status, ms): live stage events (storage mode broadcasts them over Realtime)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    videos = [videos] if isinstance(videos, (bytes, bytearray)) else list(videos)
    T = Timer(on_event)
    out: dict = {"files": {}, "coverage": "full" if len(videos) >= 2 else "top", "passes": min(len(videos), 2)}

    with T.stage("1_frames"):
        decoded = decode_all(videos[:2], cfg["n_frames"], cfg.get("rotate_cw"))
    caps = []
    for tag, (frames, video_frames) in zip(["top", "bottom"], decoded):
        c = capture(models, frames, video_frames, cfg, T, tag, out)
        if c is None:
            out["timings"] = {**T.t, "total": T.total()}
            return out
        caps.append(c)

    # the held-out photos, chosen per pass in its own scan frame, before the bottom pass is moved into the top's
    held = [heldout_mod.choose(c, k, flipped=i == 1) for i, (c, k) in
            enumerate(zip(caps, heldout_mod.counts(len(caps) == 2)))]
    out["files"].update(heldout_mod.files(caps, held, ["top", "bottom"]))

    cap = caps[0]
    tcfg = {**(cfg.get("train") or {}), "holdout_ids": held[0]}
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
        tcfg["session_split"] = tcfg.get("session_split") or n  # first n views are the top capture
        tcfg["holdout_ids"] = held[0] + [n + i for i in held[1]]
        if cfg["stop_after"] == "register":
            out["timings"] = {**T.t, "total": T.total()}
            return out

    with T.stage("4_train"):
        params, c2w_ref, views, train_ids, test_ids = train_mod.train(
            cap["c2w"], cap["K"], cap["frames"], cap["masks"], cap["pts"], cap["cols"], tcfg)

    with T.stage("5_clean_export"):
        contrib = train_mod.contribution(params, c2w_ref, views, train_ids)
        keep, cstats = export_mod.keep_mask(params, c2w_ref, cap["K"], cap["masks"], cap["stats"]["object_radius"],
                                            cfg.get("export"), contrib)
        sh_deg = {**train_mod.DEFAULTS, **tcfg}["sh_degree"]
        out["files"]["splat.spz"] = export_mod.to_spz(params, keep, sh_deg)
        if cfg["ply"]:
            out["files"]["splat.ply"] = export_mod.to_ply(params, keep)
    out["gaussians"] = cstats
    if cfg["spin"]:
        with T.stage("6_spin"):
            clean0 = {k: v[keep].detach() for k, v in params.items()}
            for name, data in spin_mod.spin_frames(clean0, sh_deg):
                out["files"][f"spin/{name}"] = data
    out["sizes_mb"] = {k: round(len(v) / 1e6, 2) for k, v in out["files"].items() if k.startswith("splat.")}
    print(f"sizes: {out['sizes_mb']}  cleanup: {cstats}", flush=True)

    out["timings"] = {**T.t, "total": T.total()}
    if cfg["debug"]:  # after the timed path: how well the splat predicts the held-out photos' frames
        t0 = time.perf_counter()
        clean = {k: torch.nn.Parameter(v[keep]) for k, v in params.items()}
        out["eval_heldout"], _ = train_mod.evaluate(clean, cap["c2w"], views, test_ids, sh_deg, pose_steps=60)
        print(f"held-out (pose-fit): {out['eval_heldout']}", flush=True)
        out["debug_extras_s"] = round(time.perf_counter() - t0, 2)
    return out
