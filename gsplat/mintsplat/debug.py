import cv2
import numpy as np


def sheet(images: list[np.ndarray], cols: int = 4, width: int = 360) -> bytes:
    """RGB images -> one JPEG contact sheet."""
    tiles = [cv2.resize(i, (width, int(width * i.shape[0] / i.shape[1]))) for i in images]
    th, tw = tiles[0].shape[:2]
    rows = -(-len(tiles) // cols)
    out = np.zeros((rows * th, cols * tw, 3), np.uint8)
    for k, t in enumerate(tiles):
        r, c = divmod(k, cols)
        out[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = t[:th, :tw]
    return cv2.imencode(".jpg", cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def overlay(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Dim the background, outline the mask in mint green."""
    out = frame.copy()
    out[~mask] = (out[~mask] * 0.35).astype(np.uint8)
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(out, cnts, -1, (61, 220, 151), 3)
    return out
