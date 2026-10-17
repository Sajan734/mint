"""Ingest finished scans from Supabase into item folders the listing pipeline can run on.

    python ingest.py <scan_id> [--seller-name "Sony WH-1000XM4"] [--run]
    python ingest.py --latest [--run]                      # the newest finished scan
    python ingest.py --watch [--interval 5] [--run]         # keep ingesting new scans as they finish

The splat job (gsplat/, role A) publishes every finished scan to the public `assets` bucket:
  splats/{scan_id}.spz          compressed splat (SPZ v3)
  splats/{scan_id}.json         manifest (inputs, timings, Gaussian count, reference view URLs)
  views/{scan_id}/...           8 reference renders + views.json (cameras)
  splats/index.json             recent scans, newest first (what --latest / --watch read)
All of that is public, so ingestion needs no key: only SUPABASE_URL (defaults to the team project).

Each scan becomes samples/<scan_id>/ (gitignored):
  splat.spz            as published (~2.5 MB; splat_render.py reads it directly, no 35 MB .ply anywhere)
  input.json           {"seller_name": ..., "up_axis": "+y"} (scans are in a +Y-up frame)
  manifest.json        the scan's manifest
  reference_views/     the 8 reference renders + views.json
so `python pipeline.py samples/<scan_id>` runs the listing pipeline on it unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
DEFAULT_SUPABASE_URL = "https://jpanyhsifoxxiizkgjno.supabase.co"  # public project URL, not a secret
BUCKET = "assets"

INGEST = {"timeout_s": 60.0, "retries": 1, "watch_interval_s": 5.0}


class IngestError(RuntimeError):
    pass


# --- SPZ check ----------------------------------------------------------------------------------------


def check_spz(data: bytes) -> int:
    """Gaussian count of a readable splat, using the renderer's own SPZ reader; IngestError otherwise."""
    import torch

    from splat_render import SplatError, parse_spz

    try:
        return len(parse_spz(data, torch.device("cpu")).means)
    except SplatError as e:
        raise IngestError(f"bad splat: {e}") from None


# --- Supabase (public bucket, no key) -------------------------------------------------------------------


def supabase_url() -> str:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    return (os.environ.get("SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")


def public_url(path: str, base: str | None = None) -> str:
    return f"{base or supabase_url()}/storage/v1/object/public/{BUCKET}/{path}"


def fetch(url: str, fresh: bool = False) -> bytes:
    """GET with a timeout and one retry. fresh=True busts CDN caching (for the index)."""
    import httpx

    if fresh:
        url += f"{'&' if '?' in url else '?'}t={int(time.time())}"
    last: Exception | None = None
    for attempt in range(INGEST["retries"] + 1):
        try:
            r = httpx.get(url, timeout=INGEST["timeout_s"], follow_redirects=True)
            if r.status_code == 404 or (r.status_code == 400 and b"not_found" in r.content):
                raise IngestError(f"not found: {url}")
            r.raise_for_status()
            return r.content
        except IngestError:
            raise
        except httpx.HTTPError as e:
            last = e
            if attempt < INGEST["retries"]:
                time.sleep(1.0)
    raise IngestError(f"download failed: {url} ({last})")


def recent_scans(base: str | None = None) -> list[dict]:
    """splats/index.json written by the splat job: [{scan_id, created_at, manifest_url}], newest first."""
    try:
        index = json.loads(fetch(public_url("splats/index.json", base), fresh=True))
    except IngestError as e:
        raise IngestError(f"no scan index yet ({e}); has the splat job published a scan?") from None
    return index.get("scans", [])


# --- ingestion ------------------------------------------------------------------------------------------


def ingest(scan_id: str, seller_name: str | None = None, root: Path = SAMPLES, base: str | None = None,
           get=fetch) -> Path:
    """Download one scan into root/<scan_id>/ and return that folder. `get` is injectable for tests."""
    base = base or supabase_url()
    manifest = json.loads(get(public_url(f"splats/{scan_id}.json", base)))
    spz = get(manifest.get("splat_url") or public_url(f"splats/{scan_id}.spz", base))
    check_spz(spz)  # fail here, not later in the render stage

    item = root / scan_id
    tmp = root / f".{scan_id}.partial"  # write fully, then rename: --watch never sees half an item
    (tmp / "reference_views").mkdir(parents=True, exist_ok=True)
    (tmp / "splat.spz").write_bytes(spz)
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    inputs = {"seller_name": seller_name, "up_axis": "+y", "scan_id": scan_id,
              "source": public_url(f"splats/{scan_id}.json", base)}
    (tmp / "input.json").write_text(json.dumps(inputs, indent=2), encoding="utf-8")

    views_url = manifest.get("views_json_url")
    if views_url:
        views = json.loads(get(views_url))
        (tmp / "reference_views" / "views.json").write_text(json.dumps(views, indent=1), encoding="utf-8")
        folder = views_url.rsplit("/", 1)[0]
        for view in views.get("views", []):
            for name in view.get("files", {}).values():
                (tmp / "reference_views" / name).write_bytes(get(f"{folder}/{name}"))

    if item.exists():
        shutil.rmtree(item)
    tmp.rename(item)
    return item


def run_listing(item: Path) -> None:
    from pipeline import run_pipeline

    result = asyncio.run(run_pipeline(item))
    print(f"{type(result).__name__}:", file=sys.stderr)
    print(result.model_dump_json(indent=2))


def watch(interval: float, seller_name: str | None, run: bool) -> None:
    """Poll the scan index and ingest every scan not yet in samples/. Ctrl+C to stop."""
    print(f"watching {public_url('splats/index.json')} every {interval:g}s (Ctrl+C to stop)", file=sys.stderr)
    while True:
        try:
            for scan in reversed(recent_scans()):  # oldest first
                if not (SAMPLES / scan["scan_id"] / "splat.spz").is_file():
                    item = ingest(scan["scan_id"], seller_name)
                    print(f"ingested {item.relative_to(ROOT)}", file=sys.stderr)
                    if run:
                        run_listing(item)
        except IngestError as e:
            print(f"waiting: {e}", file=sys.stderr)
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest finished scans from Supabase into samples/<scan_id>/.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("scan_id", nargs="?", help="scan id (a UUID) to ingest")
    which.add_argument("--latest", action="store_true", help="ingest the newest finished scan")
    which.add_argument("--watch", action="store_true", help="keep ingesting new scans as they finish")
    parser.add_argument("--seller-name", default=None, help="product name typed by the seller (input.json)")
    parser.add_argument("--run", action="store_true", help="run the listing pipeline on each ingested item")
    parser.add_argument("--interval", type=float, default=INGEST["watch_interval_s"], help="--watch poll seconds")
    args = parser.parse_args(argv)

    try:
        if args.watch:
            watch(args.interval, args.seller_name, args.run)
            return 0
        scan_id = args.scan_id
        if args.latest:
            scans = recent_scans()
            if not scans:
                raise IngestError("the scan index is empty")
            scan_id = scans[0]["scan_id"]
        item = ingest(scan_id, args.seller_name)
    except IngestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    print(item.relative_to(ROOT).as_posix())
    if args.run:
        run_listing(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
