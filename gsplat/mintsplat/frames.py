import cv2
import numpy as np

MAX_SCORED_FPS = 30  # high-frame-rate video (60/120 fps) only scores every k-th frame


def pick_frames(path: str, n: int) -> tuple[list[np.ndarray], list[int]]:
    """One decode pass; keep the sharpest frame in each of n equal time buckets.

    Returns RGB uint8 frames at the video's native resolution (no re-encode, so no
    extra compression artifacts) and their source frame indices. Above MAX_SCORED_FPS only every
    k-th frame is retrieved and scored; the rest are just grabbed (decoded, no colour conversion).
    """
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    stride = max(1, round(fps / MAX_SCORED_FPS))
    best: list[tuple[float, np.ndarray | None, int]] = [(-1.0, None, -1)] * n
    i = 0
    while True:
        if i % stride:
            if not cap.grab():
                break
            i += 1
            continue
        ok, f = cap.read()
        if not ok:
            break
        b = min(n - 1, i * n // max(total, 1))
        g = cv2.cvtColor(cv2.resize(f, (320, int(320 * f.shape[0] / f.shape[1]))), cv2.COLOR_BGR2GRAY)
        s = float(cv2.Laplacian(g, cv2.CV_32F).var())
        if s > best[b][0]:
            best[b] = (s, f, i)
        i += 1
    cap.release()
    keep = [(f, k) for _, f, k in best if f is not None]
    return [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f, _ in keep], [k for _, k in keep]
