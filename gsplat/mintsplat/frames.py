import cv2
import numpy as np

MAX_SCORED_FPS = 30  # high-frame-rate video (60/120 fps) only scores every k-th frame
ROTATIONS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def upright_rotation(poses_jsonl: bytes) -> int:
    """Clockwise degrees (0/90/180/270) that turn the Mint app's frames upright.

    The app saves frames in the sensor's landscape orientation (scanner/HANDOFF.md) while the phone is held upright,
    so the item lies on its side. Each poses.jsonl line has the raw ARKit camera-to-world `pose_world` (camera axes
    x right, y up = the stored image's axes; world +Y = up). World up in camera axes is the second row of the
    rotation; the image axis it points along (majority over frames) says which edge of the image is up."""
    import json

    votes = {0: 0, 90: 0, 180: 0, 270: 0}
    for line in poses_jsonl.decode("utf-8", errors="replace").splitlines():
        try:
            pose = json.loads(line).get("pose_world")
        except json.JSONDecodeError:
            continue
        if not pose:
            continue
        ux, uy = pose[1][0], pose[1][1]  # world up along the image's x (right) and y (up) axes
        if abs(uy) >= abs(ux):
            votes[0 if uy > 0 else 180] += 1
        else:  # up is the right edge: turn 90 deg counter-clockwise; the left edge: 90 deg clockwise
            votes[270 if ux > 0 else 90] += 1
    return max(votes, key=votes.get) if any(votes.values()) else 0


def pick_frames(path: str, n: int, rotate_cw: int = 0) -> tuple[list[np.ndarray], list[int]]:
    """One decode pass; keep the sharpest frame in each of n equal time buckets.

    Returns RGB uint8 frames at the video's native resolution (no re-encode, so no
    extra compression artifacts) and their source frame indices. Above MAX_SCORED_FPS only every
    k-th frame is retrieved and scored; the rest are just grabbed (decoded, no colour conversion).
    rotate_cw turns the kept frames upright (upright_rotation); sharpness doesn't depend on it.
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
    keep = [(f if rotate_cw not in ROTATIONS else cv2.rotate(f, ROTATIONS[rotate_cw]), k)
            for _, f, k in best if f is not None]
    return [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f, _ in keep], [k for _, k in keep]
