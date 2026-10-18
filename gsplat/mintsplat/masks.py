import cv2
import numpy as np


MASK = {
    "min_part_frac": 0.015,  # extra connected pieces at least this share of the main body are kept ...
    "part_reach": 0.25,      # ... if their centre lies within the main body's box grown by this fraction
    "box_grow": 0.12,  # box re-prompt: first-frame point mask's box grown by this share of its size per side
}


def outline(m: np.ndarray) -> np.ndarray:
    """The item's outline (convex hull), filled: everything inside it is the item. SAM 2 drops parts that look
    different from the body (a mouse's red button, logos, highlights) as holes or as notches in the silhouette;
    training would then make them see-through. The hull keeps them all. An item with real hollows (a chair) gets
    the background in them too; compact items (the demo's mouse) are what we scan."""
    pts = cv2.findNonZero(m.astype(np.uint8))
    if pts is None:
        return m.astype(bool)
    out = np.zeros(m.shape, np.uint8)
    cv2.fillConvexPoly(out, cv2.convexHull(pts), 1)
    return out.astype(bool)


def main_parts(m: np.ndarray) -> np.ndarray:
    """Largest blob plus sizeable pieces next to it (a leg split off by occlusion), minus distant specks."""
    n, lab, stats, cents = cv2.connectedComponentsWithStats(m.astype(np.uint8))
    if n <= 1:
        return m.astype(bool)
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = 1 + areas.argmax()
    x, y, bw, bh = stats[big, :4]
    gx, gy = MASK["part_reach"] * bw, MASK["part_reach"] * bh
    keep = np.zeros(n, bool)
    for i in range(1, n):
        cx, cy = cents[i]
        near = x - gx <= cx <= x + bw + gx and y - gy <= cy <= y + bh + gy
        keep[i] = i == big or (stats[i, cv2.CC_STAT_AREA] >= MASK["min_part_frac"] * areas.max() and near)
    return keep[lab]


def clean(m: np.ndarray) -> np.ndarray:
    return outline(main_parts(m))


class Segmenter:
    """SAM 2 video predictor: prompt the first frame once, propagate through the rest with memory.

    Temporal propagation keeps the same object every frame (per-frame prompting can
    flip to a part such as the trackpoint, or to the paper).
    """

    def __init__(self, model_id: str = "facebook/sam2.1-hiera-small"):
        from sam2.sam2_video_predictor import SAM2VideoPredictor

        self.pred = SAM2VideoPredictor.from_pretrained(model_id)

    def __call__(self, frames: list[np.ndarray], box: list[float] | None = None,
                 box_refine: bool = True) -> list[np.ndarray]:
        import sam2.sam2_video_predictor as vp
        import torch

        h, w = frames[0].shape[:2]
        size = self.pred.image_size
        # Same preprocessing as SAM 2's JPEG-folder loader (square resize, ImageNet norm), done on
        # the GPU straight from memory instead of a JPEG write + read round trip (~2-3 s / video).
        x = torch.from_numpy(np.stack(frames)).cuda().permute(0, 3, 1, 2).float() / 255
        x = torch.nn.functional.interpolate(x, size=(size, size), mode="bicubic", antialias=True).clamp(0, 1)
        mean = torch.tensor([0.485, 0.456, 0.406], device="cuda")[:, None, None]
        std = torch.tensor([0.229, 0.224, 0.225], device="cuda")[:, None, None]
        images = (x - mean) / std

        loader = vp.load_video_frames
        vp.load_video_frames = lambda **_: (images, h, w)
        try:
            with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                state = self.pred.init_state(video_path="<in-memory>")
                if box is not None:
                    self.pred.add_new_points_or_box(state, frame_idx=0, obj_id=1, box=np.array(box, np.float32))
                else:
                    # orbit videos keep the object near the centre; a small cross of positives
                    # covers the body rather than one part of it
                    pts = np.array([[w / 2, h / 2], [w * 0.42, h / 2], [w * 0.58, h / 2],
                                    [w / 2, h * 0.42], [w / 2, h * 0.58]], np.float32)
                    labels = np.ones(len(pts), np.int32)
                    _, _, logits = self.pred.add_new_points_or_box(state, frame_idx=0, obj_id=1, points=pts,
                                                                   labels=labels)
                    m0 = clean((logits[0, 0] > 0).cpu().numpy())
                    if box_refine and m0.any():
                        # Re-prompt with the point mask's box grown a little, plus the same points: a box
                        # asks SAM for the whole thing inside it, which pulls in attached parts (a phone's
                        # stand, a lamp's base) that the point prompt alone leaves out.
                        ys, xs = np.nonzero(m0)
                        gx, gy = MASK["box_grow"] * (xs.ptp() + 1), MASK["box_grow"] * (ys.ptp() + 1)
                        grown = np.array([max(0, xs.min() - gx), max(0, ys.min() - gy),
                                          min(w - 1, xs.max() + gx), min(h - 1, ys.max() + gy)], np.float32)
                        self.pred.reset_state(state)
                        self.pred.add_new_points_or_box(state, frame_idx=0, obj_id=1, points=pts, labels=labels,
                                                        box=grown)
                out: dict[int, np.ndarray] = {}
                for fi, _, logits in self.pred.propagate_in_video(state):
                    out[fi] = (logits[0, 0] > 0).cpu().numpy()
                self.pred.reset_state(state)
        finally:
            vp.load_video_frames = loader
        return [clean(out[i]) for i in range(len(frames))]


def sane(masks: list[np.ndarray]) -> list[bool]:
    """Reject empty / frame-filling / wildly off-median masks (lost track, hand grabbed, etc.)."""
    areas = np.array([m.mean() for m in masks])
    med = np.median(areas[areas > 0]) if (areas > 0).any() else 0.0
    return [bool(0.01 < a < 0.85 and 0.4 * med < a < 2.5 * med) for a in areas]
