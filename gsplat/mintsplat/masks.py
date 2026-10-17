import cv2
import numpy as np


def fill_holes(m: np.ndarray) -> np.ndarray:
    """Object outline only: anything the object encloses (logo, trackpoint, specular patches) is object.

    Background = pixels connected to the image border; everything else is filled in.
    """
    h, w = m.shape
    pad = np.zeros((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = m.astype(np.uint8)
    cv2.floodFill(pad, None, (0, 0), 2)
    return pad[1:-1, 1:-1] != 2


def largest_blob(m: np.ndarray) -> np.ndarray:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
    if n <= 1:
        return m.astype(bool)
    return lab == 1 + stats[1:, cv2.CC_STAT_AREA].argmax()


def clean(m: np.ndarray) -> np.ndarray:
    m = largest_blob(m)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)).astype(bool)
    return fill_holes(m)


class Segmenter:
    """SAM 2 video predictor: prompt the first frame once, propagate through the rest with memory.

    Temporal propagation keeps the same object every frame (per-frame prompting can
    flip to a part such as the trackpoint, or to the paper).
    """

    def __init__(self, model_id: str = "facebook/sam2.1-hiera-small"):
        from sam2.sam2_video_predictor import SAM2VideoPredictor

        self.pred = SAM2VideoPredictor.from_pretrained(model_id)

    def __call__(self, frames: list[np.ndarray], box: list[float] | None = None) -> list[np.ndarray]:
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
                    self.pred.add_new_points_or_box(state, frame_idx=0, obj_id=1, points=pts,
                                                    labels=np.ones(len(pts), np.int32))
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
