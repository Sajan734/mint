"""Storage mode I/O around the pipeline: fetch a scan's videos from Supabase, publish the results.

`sb` is a supabase_setup.storage.Supabase (or anything with the same methods), so this runs unchanged
against an in-memory fake in tests.

Published layout (public `assets` bucket, readable without a key):
  splats/{scan_id}.spz      the splat (SPZ v3)
  splats/{scan_id}.json     manifest
  views/{scan_id}/          8 reference views (transparent + grey PNG each) + views.json (cameras)
                            + spin/f00..f23.webp (turntable for the website's spin viewer)
  splats/index.json         every published scan, newest first (listing/ingest.py polls this)
The .spz is the only splat format that leaves the GPU: ~10x smaller than a PLY, and listing/ renders it directly.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

SCANS, ASSETS = "scans", "assets"
VIDEO_EXTS = (".mp4", ".mov", ".m4v")
TOP_NAMES, BOTTOM_NAMES = ("top", "video"), ("bottom",)  # video.mp4 is what the iOS app uploads
CONTENT_TYPES = {".json": "application/json", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg"}


VERIFY_TOP_NAMES, VERIFY_BOTTOM_NAMES = ("rescan",), ("rescan2",)  # a buyer's verify rescan (scanner/HANDOFF.md)


def fetch_inputs(sb, scan_id: str, verify: bool = False) -> tuple[list[str], list[bytes], dict]:
    """scans/{scan_id}/top.* or video.* (required) and bottom.* (optional) -> (names, video bytes, io timings).
    io["rotate_cw"] turns each video's frames upright, from the app's poses.jsonl / bottom.poses.jsonl when
    present (its frames are stored sideways); 0 for videos without one. io["session"] is the scan's session.json
    (scanner/DASHBOARD.md: the product title the seller typed, seller, kind) when there is one."""
    import json

    from .frames import upright_rotation

    t0 = time.perf_counter()
    names = sb.list(SCANS, scan_id)
    videos = sorted(n for n in names if n.lower().endswith(VIDEO_EXTS))
    pick = lambda roles: next((n for n in videos if n.rsplit(".", 1)[0] in roles), None)  # noqa: E731
    top, bottom = (VERIFY_TOP_NAMES, VERIFY_BOTTOM_NAMES) if verify else (TOP_NAMES, BOTTOM_NAMES)
    keys = [k for k in (pick(top), pick(bottom)) if k]
    if not keys or keys[0].rsplit(".", 1)[0] not in top:
        raise FileNotFoundError(f"no scans/{scan_id}/{top[0]}.mp4 uploaded (found {names})")
    poses = [("poses.jsonl" if k.startswith("video.") else f"{k.rsplit('.', 1)[0]}.poses.jsonl") for k in keys]
    poses = [p if p in names else None for p in poses]
    with ThreadPoolExecutor(4) as ex:
        videos = list(ex.map(lambda k: sb.download(SCANS, f"{scan_id}/{k}"), keys))
        rotate = list(ex.map(lambda p: upright_rotation(sb.download(SCANS, f"{scan_id}/{p}")) if p else 0, poses))
    session = None
    if "session.json" in names:
        try:
            raw = json.loads(sb.download(SCANS, f"{scan_id}/session.json"))
            session = {k: raw.get(k) for k in ("title", "seller", "kind", "source")}
        except (RuntimeError, ValueError):
            session = None
    io = {"download_s": round(time.perf_counter() - t0, 2), "download_mb": round(sum(map(len, videos)) / 1e6, 1),
          "rotate_cw": rotate, "session": session}
    return keys, videos, io


def publish(sb, scan_id: str, batch_id: str, keys: list[str], res: dict, io: dict, index: bool = True) -> dict:
    """Upload the pipeline result `res` (with res["files"]) to the public bucket; return the manifest."""
    files = dict(res["files"])
    t0 = time.perf_counter()
    folder = f"views/{scan_id}"
    targets = [(f"splats/{scan_id}.spz", files.pop("splat.spz"), "application/octet-stream")]
    targets += [(f"{folder}/{k.split('/', 1)[1]}", v, CONTENT_TYPES["." + k.rsplit(".", 1)[-1]])
                for k, v in files.items() if k.startswith("views/")]
    with ThreadPoolExecutor(8) as ex:
        urls = dict(zip([p for p, _, _ in targets], ex.map(lambda x: sb.upload(ASSETS, *x), targets)))
    io["upload_s"] = round(time.perf_counter() - t0, 2)
    io["upload_mb"] = round(sum(len(d) for _, d, _ in targets) / 1e6, 2)

    meta = json.loads(files["views/views.json"])
    manifest = {
        "v": 3, "scan_id": scan_id, "batch_id": batch_id, "inputs": [f"{SCANS}/{scan_id}/{k}" for k in keys],
        "splat_path": f"{ASSETS}/splats/{scan_id}.spz", "splat_url": urls[f"splats/{scan_id}.spz"],
        "views_json_url": urls[f"{folder}/views.json"],
        "views": {"layout": meta["layout"], "includes_bottom": meta["includes_bottom"], "items": [
            {"name": v["name"], "azimuth_deg": v["azimuth_deg"], "elevation_deg": v["elevation_deg"],
             "transparent_url": urls[f"{folder}/{v['files']['transparent']}"],
             "grey_url": urls[f"{folder}/{v['files']['grey']}"]} for v in meta["views"]]},
        "spin_urls": [urls[p] for p in sorted(p for p in urls if p.startswith(f"{folder}/spin/"))],
        "metric_scale": None,  # video-only scans are not metric yet
        "frame": "scan frame: +Y up, +X along the object's long axis, origin under the object, right-handed (SPZ's RUB)",
        "gaussians": res["gaussians"]["after"], "sizes_mb": res["sizes_mb"],
        "stage_timings_ms": {k: int(v * 1000) for k, v in res["timings"].items()},
        "register": res.get("register"), "io": io,
    }
    sb.upload(ASSETS, f"splats/{scan_id}.json", json.dumps(manifest, indent=1).encode(), "application/json")
    if index:  # a buyer's rescan is not a scan to list, so listing/ingest.py must not see it
        refresh_index(sb)
    return manifest


def refresh_index(sb) -> dict:
    """Rebuild splats/index.json from the folder listing (not read-modify-write, so scans that finish at the
    same time can't drop each other's entry). no-cache, so pollers never see a stale CDN copy."""
    objs = [o for o in sb.list_objects(ASSETS, "splats") if o["name"].endswith(".json") and o["name"] != "index.json"]
    index = {"v": 3, "updated_at": datetime.now(timezone.utc).isoformat(), "scans": [
        {"scan_id": o["name"].removesuffix(".json"), "created_at": o.get("created_at"),
         "manifest_url": sb.public_url(ASSETS, f"splats/{o['name']}")} for o in objs]}
    sb.upload(ASSETS, "splats/index.json", json.dumps(index, indent=1).encode(), "application/json",
              cache_control="no-cache")
    return index
