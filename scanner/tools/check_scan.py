#!/usr/bin/env python3
"""Check a Mint scan folder (or its .zip) before anyone trains on it.

  python check_scan.py path/to/scan_or_zip [--overlays out_dir]

Checks:
  1. manifest.json validates against contracts/capture_manifest.schema.json (v3).
  2. video.mp4 decodes to exactly as many frames as poses.jsonl has lines, at the stated size.
  3. Every keyframe JPEG exists, has the manifest's size, and matches its sha256.
  4. Pose + intrinsics sanity: the item centre (manifest anchor) projects inside every keyframe and
     every tracked video frame, in front of the camera. Overlays (a crosshair on the item) are
     written for a sample, so a human can confirm the poses and K line up.
Exit code 0 = all good.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO / "contracts"
ARKIT_TO_CV = np.diag([1.0, -1.0, -1.0, 1.0])


def load_scan(path: Path) -> Path:
    if path.suffix == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="mint-scan-"))
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        hits = list(tmp.rglob("manifest.json"))
        if not hits:
            sys.exit("no manifest.json in zip")
        return hits[0].parent
    return path


def project(world_pt: np.ndarray, pose_rowmajor, k_rowmajor) -> tuple[float, float, float]:
    """Raw ARKit camera-to-world pose → pixel (u, v) and depth along the optical axis."""
    t_cv = np.asarray(pose_rowmajor, dtype=np.float64) @ ARKIT_TO_CV  # camera-to-world, OpenCV axes
    pc = np.linalg.inv(t_cv) @ np.append(world_pt, 1.0)
    uvw = np.asarray(k_rowmajor, dtype=np.float64) @ pc[:3]
    return uvw[0] / uvw[2], uvw[1] / uvw[2], pc[2]


def crosshair(img, u, v, colour=(151, 220, 61)):
    u, v = int(round(u)), int(round(v))
    cv2.drawMarker(img, (u, v), colour, cv2.MARKER_CROSS, 40, 3)
    cv2.circle(img, (u, v), 26, colour, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scan", type=Path)
    ap.add_argument("--overlays", type=Path, help="write crosshair overlays here")
    args = ap.parse_args()
    scan = load_scan(args.scan)
    problems: list[str] = []

    manifest = json.loads((scan / "manifest.json").read_text())
    capture = json.loads((scan / "capture.json").read_text())
    poses = [json.loads(line) for line in (scan / "poses.jsonl").read_text().splitlines() if line.strip()]

    # 1. Schema
    try:
        import jsonschema
        from referencing import Registry, Resource

        resources = [(p.name, Resource.from_contents(json.loads(p.read_text()))) for p in SCHEMA_DIR.glob("*.schema.json")]
        registry = Registry().with_resources(resources + [(f"mint/{n}", r) for n, r in resources])
        schema = json.loads((SCHEMA_DIR / "capture_manifest.schema.json").read_text())
        errors = list(jsonschema.Draft202012Validator(schema, registry=registry).iter_errors(manifest))
        for e in errors[:10]:
            problems.append(f"manifest schema: {'/'.join(map(str, e.path))}: {e.message}")
        print(f"schema: {'ok' if not errors else f'{len(errors)} errors'}")
    except ImportError:
        print("schema: skipped (pip install jsonschema)")

    # 2. Video ↔ poses
    cap = cv2.VideoCapture(str(scan / capture["video"]))
    frames: list[np.ndarray] = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    h, w = (frames[0].shape[:2] if frames else (0, 0))
    print(f"video: {len(frames)} frames {w}x{h}, poses.jsonl: {len(poses)} lines, {capture['duration_ms'] / 1000:.1f} s")
    if len(frames) != len(poses):
        problems.append(f"video has {len(frames)} frames but poses.jsonl has {len(poses)} lines")
    if (w, h) != (capture["video_width"], capture["video_height"]):
        problems.append(f"video is {w}x{h}, capture.json says {capture['video_width']}x{capture['video_height']}")
    if [p["frame"] for p in poses] != list(range(len(poses))):
        problems.append("poses.jsonl frame numbers aren't 0..n-1 in order")

    # 3. Keyframes
    for f in manifest["frames"]:
        p = scan / Path(f["path"]).name
        if not p.exists():
            problems.append(f"missing keyframe {p.name}")
            continue
        data = p.read_bytes()
        if f.get("sha256") and hashlib.sha256(data).hexdigest() != f["sha256"]:
            problems.append(f"{p.name}: sha256 mismatch")
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img.shape[1::-1] != (manifest["width"], manifest["height"]):
            problems.append(f"{p.name}: {img.shape[1]}x{img.shape[0]}, manifest says {manifest['width']}x{manifest['height']}")
    print(f"keyframes: {len(manifest['frames'])}")

    # 4. Projection of the item centre
    centre = np.asarray(manifest["anchor"], dtype=np.float64)

    def check(label, pose, k, width, height):
        u, v, z = project(centre, pose, k)
        if z <= 0:
            problems.append(f"{label}: item centre is behind the camera")
        elif not (0 <= u < width and 0 <= v < height):
            problems.append(f"{label}: item centre projects outside the image at ({u:.0f}, {v:.0f})")

    for f in manifest["frames"]:
        check(Path(f["path"]).name, f["pose"], f["intrinsics"], manifest["width"], manifest["height"])
    tracked = [p for p in poses if p.get("pose") is not None]
    for p in tracked:
        check(f"video frame {p['frame']}", p["pose"], p["intrinsics"], w, h)
    print(f"projection: checked {len(manifest['frames'])} keyframes + {len(tracked)} video frames")

    if args.overlays:
        args.overlays.mkdir(parents=True, exist_ok=True)
        for f in manifest["frames"][:: max(1, len(manifest["frames"]) // 6)]:
            img = cv2.imread(str(scan / Path(f["path"]).name))
            crosshair(img, *project(centre, f["pose"], f["intrinsics"])[:2])
            cv2.imwrite(str(args.overlays / f"kf_{Path(f['path']).stem}.jpg"), img)
        for p in tracked[:: max(1, len(tracked) // 6)]:
            if p["frame"] < len(frames):
                img = frames[p["frame"]].copy()
                crosshair(img, *project(centre, p["pose"], p["intrinsics"])[:2])
                cv2.imwrite(str(args.overlays / f"video_{p['frame']:05d}.jpg"), img)
        print(f"overlays: {args.overlays}")

    for p in problems[:30]:
        print("PROBLEM:", p)
    print("OK" if not problems else f"{len(problems)} problems")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
