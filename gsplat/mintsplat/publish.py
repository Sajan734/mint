"""Storage mode I/O around the pipeline: fetch a scan's videos from Supabase, publish the results.

`sb` is a supabase_setup.storage.Supabase (or anything with the same methods), so this runs unchanged
against an in-memory fake in tests.

Published layout (public `assets` bucket, readable without a key):
  splats/{scan_id}.spz      the splat (SPZ v3)
  splats/{scan_id}.json     manifest
  views/{scan_id}/          8 reference views (transparent + grey PNG each) + views.json (cameras)
  splats/index.json         every published scan, newest first (listing/ingest.py polls this)
Private: /work/{scan_id}/splat.ply + views.json on the mint-work Volume (full precision, for B).
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SCANS, ASSETS = "scans", "assets"


def fetch_inputs(sb, scan_id: str) -> tuple[list[str], list[bytes], dict]:
    """scans/{scan_id}/top.* (required) and bottom.* (optional) -> (names, video bytes, io timings)."""
    t0 = time.perf_counter()
    names = sb.list(SCANS, scan_id)
    pick = lambda role: next((n for n in sorted(names) if n.startswith(role + ".")), None)  # noqa: E731
    keys = [k for k in (pick("top"), pick("bottom")) if k]
    if not keys or not keys[0].startswith("top."):
        raise FileNotFoundError(f"no scans/{scan_id}/top.* uploaded (found {names})")
    with ThreadPoolExecutor(2) as ex:
        videos = list(ex.map(lambda k: sb.download(SCANS, f"{scan_id}/{k}"), keys))
    io = {"download_s": round(time.perf_counter() - t0, 2), "download_mb": round(sum(map(len, videos)) / 1e6, 1)}
    return keys, videos, io


def publish(sb, scan_id: str, batch_id: str, keys: list[str], res: dict, work_dir: Path, io: dict) -> dict:
    """Write the pipeline result `res` (with res["files"]) to the Volume and the public bucket; return the manifest."""
    files = dict(res["files"])
    t0 = time.perf_counter()
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "splat.ply").write_bytes(files.pop("splat.ply"))
    (work_dir / "views.json").write_bytes(files["views/views.json"])
    io["ply_to_volume_s"] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    folder = f"views/{scan_id}"
    targets = [(f"splats/{scan_id}.spz", files.pop("splat.spz"), "application/octet-stream")]
    targets += [(f"{folder}/{k.split('/', 1)[1]}", v, "application/json" if k.endswith(".json") else "image/png")
                for k, v in files.items() if k.startswith("views/")]
    with ThreadPoolExecutor(8) as ex:
        urls = dict(zip([p for p, _, _ in targets], ex.map(lambda x: sb.upload(ASSETS, *x), targets)))
    io["upload_s"] = round(time.perf_counter() - t0, 2)
    io["upload_mb"] = round(sum(len(d) for _, d, _ in targets) / 1e6, 2)

    meta = json.loads(files["views/views.json"])
    manifest = {
        "v": 3, "scan_id": scan_id, "batch_id": batch_id, "inputs": [f"{SCANS}/{scan_id}/{k}" for k in keys],
        "splat_path": f"{ASSETS}/splats/{scan_id}.spz", "splat_url": urls[f"splats/{scan_id}.spz"],
        "splat_ply_path": f"mint-work/{scan_id}/splat.ply",
        "views_json_url": urls[f"{folder}/views.json"],
        "views": {"layout": meta["layout"], "includes_bottom": meta["includes_bottom"], "items": [
            {"name": v["name"], "azimuth_deg": v["azimuth_deg"], "elevation_deg": v["elevation_deg"],
             "transparent_url": urls[f"{folder}/{v['files']['transparent']}"],
             "grey_url": urls[f"{folder}/{v['files']['grey']}"]} for v in meta["views"]]},
        "metric_scale": None,  # video-only scans are not metric yet
        "frame": "scan frame: +Y up, +X along the object's long axis, origin under the object, right-handed (SPZ's RUB)",
        "gaussians": res["gaussians"]["after"], "sizes_mb": res["sizes_mb"],
        "stage_timings_ms": {k: int(v * 1000) for k, v in res["timings"].items()},
        "register": res.get("register"), "io": io,
    }
    sb.upload(ASSETS, f"splats/{scan_id}.json", json.dumps(manifest, indent=1).encode(), "application/json")
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
