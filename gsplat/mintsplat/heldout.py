"""The 8 held-out photos of every scan: real video frames, masked to the item, for the agents (identify, Google
Lens search through Serper, which needs real photos at public URLs) and the website.

Picked after the poses stage, spread around the item (azimuth in each capture's scan frame, measured from the
item's long axis +X toward +Z, as everywhere in the pipeline):
  - one video (top only)       -> 8 frames, one every 45 deg
  - two videos (top + bottom)  -> 6 from the upright lap (every 60 deg) + 2 from the flipped-over lap (opposite
                                  sides), so the underside, where labels and model stickers usually are, is included
In each direction the photo is the best frame for finding the exact product online: the sharpest (logos and
printed text readable), with the item biggest in frame and fully in view, from a product-photo angle (upright
lap: about 35 deg above; flipped-over lap: looking straight at the underside and its label). The picks are held
out of training, so the splat never saw them (debug runs measure PSNR on exactly these frames).

Each photo: the frame cropped to a square around the item's outline (masks.outline: everything inside it is
kept), with a margin, everything outside white, HELDOUT["size_px"] square JPEG. heldout.json says where each was
taken from and how it scored.
"""
import json

import cv2
import numpy as np
import torch

HELDOUT = {
    "count": 8,
    "bottom_count": 2,  # of the 8, from the flipped-over lap when there is one
    "size_px": 768,
    "margin": 0.12,  # of the item's larger side, on every side of the crop
    "border_px": 3,  # a mask this close to the frame's edge means the item is cut off
    "cut_off_factor": 0.2,  # a cut-off item's score is multiplied by this
    "top_elevation_deg": 35.0,  # the upright lap's best angle (product photos); the flipped lap prefers 90
    "elevation_width_deg": 40.0,  # score halves this far from the preferred elevation
    "area_power": 0.5,  # how much a bigger item counts against sharpness
    "feather_px": 1.5,  # softens the mask edge against the white
    "background_rgb": (255, 255, 255),
    "jpeg_quality": 92,
}


def camera_angles(c2w: torch.Tensor, center: torch.Tensor) -> tuple[np.ndarray, np.ndarray]:
    """(azimuth, elevation) in degrees of each camera around `center` (scan frame, +Y up)."""
    p = (c2w[:, :3, 3] - center).cpu().numpy()
    az = np.degrees(np.arctan2(p[:, 2], p[:, 0])) % 360
    el = np.degrees(np.arctan2(p[:, 1], np.hypot(p[:, 0], p[:, 2])))
    return az, el


def cut_off(mask: np.ndarray) -> bool:
    b = HELDOUT["border_px"]
    return bool(mask[:b].any() or mask[-b:].any() or mask[:, :b].any() or mask[:, -b:].any())


def sharpness(frame: np.ndarray, mask: np.ndarray) -> float:
    """Variance of the Laplacian inside the item: high when its edges, logos and text are crisp."""
    inner = cv2.erode(mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    if inner.sum() < 100:
        return 0.0
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), cv2.CV_32F)[inner].var())


def scores(sharp: np.ndarray, area: np.ndarray, el: np.ndarray, cut: list[bool], best_el: float) -> np.ndarray:
    s = (sharp / max(sharp.max(), 1e-9)) * (area / max(area.max(), 1e-9)) ** HELDOUT["area_power"]
    s = s * 0.5 ** (np.abs(el - best_el) / HELDOUT["elevation_width_deg"])
    return s * np.where(cut, HELDOUT["cut_off_factor"], 1.0)


def pick(azimuths: np.ndarray, score: np.ndarray, k: int) -> list[int]:
    """k frame indices, one per 360/k deg sector of azimuth (centred on 0, the item's long axis, then every
    360/k deg): the best-scoring frame in each; an empty sector takes the frame closest to its centre. No frame
    twice. Fewer than k frames -> all of them."""
    if k <= 0:
        return []
    if len(azimuths) <= k:
        return list(range(len(azimuths)))
    chosen: list[int] = []
    for t in range(k):
        d = np.abs((azimuths - t * 360 / k + 180) % 360 - 180)
        free = np.ones(len(d), bool)
        free[chosen] = False
        inside = free & (d <= 180 / k)
        chosen.append(int(np.argmax(np.where(inside, score, -1.0))) if inside.any()
                      else int(np.argmin(np.where(free, d, np.inf))))
    return chosen


def photo(frame: np.ndarray, mask: np.ndarray) -> bytes:
    """RGB frame + bool mask -> square JPEG of the item on white."""
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    side = max(y1 - y0, x1 - x0) * (1 + 2 * HELDOUT["margin"])
    cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
    # square crop around the item; parts outside the frame are white
    s = HELDOUT["size_px"] / side
    M = np.array([[s, 0, HELDOUT["size_px"] / 2 - s * cx], [0, s, HELDOUT["size_px"] / 2 - s * cy]], np.float32)
    size = (HELDOUT["size_px"], HELDOUT["size_px"])
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    rgb = cv2.warpAffine(frame, M, size, flags=interp, borderValue=HELDOUT["background_rgb"]).astype(np.float32)
    a = cv2.warpAffine(mask.astype(np.float32), M, size, flags=cv2.INTER_LINEAR, borderValue=0)
    a = cv2.GaussianBlur(a, (0, 0), HELDOUT["feather_px"])[..., None].clip(0, 1)
    out = rgb * a + np.array(HELDOUT["background_rgb"], np.float32) * (1 - a)
    bgr = cv2.cvtColor(out.round().clip(0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    return cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, HELDOUT["jpeg_quality"]])[1].tobytes()


def choose(cap: dict, k: int, flipped: bool = False) -> list[int]:
    """The held-out frames of one capture (masks -> poses done): indices into cap["frames"]. Sets
    cap["heldout_scores"]. flipped: the item lies upside down, so the best view looks straight down at it."""
    az, el = camera_angles(cap["c2w"], cap["pts"].median(0).values)
    sharp = np.array([sharpness(f, m) for f, m in zip(cap["frames"], cap["masks"])])
    area = np.array([m.mean() for m in cap["masks"]])
    cap["heldout_scores"] = scores(sharp, area, el, [cut_off(m) for m in cap["masks"]],
                                   90.0 if flipped else HELDOUT["top_elevation_deg"])
    return pick(az, cap["heldout_scores"], k)


def files(caps: list[dict], held: list[list[int]], tags: list[str]) -> dict[str, bytes]:
    """{"heldout/00.jpg": ..., "heldout/heldout.json": ...} for the held-out frames of every capture."""
    out, items = {}, []
    for cap, ids, tag in zip(caps, held, tags):
        az, el = camera_angles(cap["c2w"], cap["pts"].median(0).values)
        for i in ids:
            name = f"{len(items):02d}.jpg"
            out[f"heldout/{name}"] = photo(cap["frames"][i], cap["masks"][i])
            items.append({"file": name, "pass": tag, "video_frame": int(cap["video_frames"][i]),
                          "azimuth_deg": round(float(az[i]), 1), "elevation_deg": round(float(el[i]), 1),
                          "item_cut_off": cut_off(cap["masks"][i]),
                          "score": round(float(cap["heldout_scores"][i]), 3)})
    meta = {"v": 1, "size_px": HELDOUT["size_px"], "background_rgb": list(HELDOUT["background_rgb"]),
            "angles": "camera around the item in that pass's scan frame: azimuth from the item's long axis (+X) "
                      "toward +Z, elevation above the ground (a flipped-over pass sees the underside from above)",
            "items": items}
    out["heldout/heldout.json"] = json.dumps(meta, indent=1).encode()
    return out


def counts(two_passes: bool) -> tuple[int, int]:
    """Held-out photos from (the upright lap, the flipped-over lap)."""
    bottom = HELDOUT["bottom_count"] if two_passes else 0
    return HELDOUT["count"] - bottom, bottom
