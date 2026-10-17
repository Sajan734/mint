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
  splat.spz            as published
  splat.ply            the same splat as standard 3DGS PLY, which splat_render.py reads
  input.json           {"seller_name": ..., "up_axis": "+y"} (scans are in a +Y-up frame)
  manifest.json        the scan's manifest
  reference_views/     the 8 reference renders + views.json
so `python pipeline.py samples/<scan_id>` runs the listing pipeline on it unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
DEFAULT_SUPABASE_URL = "https://jpanyhsifoxxiizkgjno.supabase.co"  # public project URL, not a secret
BUCKET = "assets"

INGEST = {"timeout_s": 60.0, "retries": 1, "watch_interval_s": 5.0}


class IngestError(RuntimeError):
    pass


# --- SPZ decoding (Niantic SPZ v2/v3, gzip container) -------------------------------------------------
# Mirrors the reference decoder (nianticlabs/spz, src/cc/load-spz.cc and splat-utils.h). Pure numpy, so the
# listing machine needs no C++ build. Version 4 (zstd streams) is not supported; the splat job writes v3.

SPZ_MAGIC = 0x5053474E  # "NGSP"
SPZ_COLOR_SCALE = 0.15
SPZ_SH_DIM = {0: 0, 1: 3, 2: 8, 3: 15, 4: 24}


def decode_spz(data: bytes) -> dict:
    """SPZ bytes -> dict of float32 arrays in the file's coordinates (RUB for the splat job's files).

    positions (N,3), scales (N,3) log, rotations (N,4) xyzw unit, alphas (N,) logit, colors (N,3) SH DC,
    sh (N, dim, 3) higher-order SH (dim 0 for degree 0), plus sh_degree and version."""
    try:
        raw = gzip.decompress(data)
    except OSError as e:
        if data[:4] == struct.pack("<I", SPZ_MAGIC):
            raise IngestError("SPZ version 4 (zstd) is not supported; the splat job writes version 3") from e
        raise IngestError("not an SPZ file (gzip header missing)") from e
    if len(raw) < 16:
        raise IngestError("SPZ file is truncated")
    magic, version, n, sh_degree, frac_bits, _flags, _ = struct.unpack_from("<IIIBBBB", raw, 0)
    if magic != SPZ_MAGIC:
        raise IngestError("not an SPZ file (bad magic)")
    if version not in (2, 3):
        raise IngestError(f"SPZ version {version} is not supported (2 and 3 are)")
    if sh_degree not in SPZ_SH_DIM:
        raise IngestError(f"unsupported SH degree {sh_degree}")
    dim = SPZ_SH_DIM[sh_degree]
    rot_bytes = 4 if version >= 3 else 3
    sizes = {"positions": n * 9, "alphas": n, "colors": n * 3, "scales": n * 3, "rotations": n * rot_bytes,
             "sh": n * dim * 3}
    if 16 + sum(sizes.values()) > len(raw):
        raise IngestError("SPZ file is truncated")
    offset, streams = 16, {}
    for name, size in sizes.items():  # stream order is fixed by the format
        streams[name] = np.frombuffer(raw, np.uint8, size, offset)
        offset += size

    p = streams["positions"].reshape(n * 3, 3).astype(np.int32)
    fixed = p[:, 0] | (p[:, 1] << 8) | (p[:, 2] << 16)
    fixed = np.where(fixed & 0x800000, fixed - (1 << 24), fixed)  # sign-extend 24-bit
    positions = (fixed.astype(np.float32) / (1 << frac_bits)).reshape(n, 3)

    scales = (streams["scales"].astype(np.float32) / 16.0 - 10.0).reshape(n, 3)
    a = np.clip(streams["alphas"].astype(np.float32) / 255.0, 0.5 / 255, 1 - 0.5 / 255)  # keep logits finite
    alphas = np.log(a / (1 - a))
    colors = ((streams["colors"].astype(np.float32) / 255.0 - 0.5) / SPZ_COLOR_SCALE).reshape(n, 3)
    sh = ((streams["sh"].astype(np.float32) - 128.0) / 128.0).reshape(n, dim, 3)

    if version >= 3:
        rotations = _smallest_three(streams["rotations"].reshape(n, 4))
    else:
        xyz = streams["rotations"].reshape(n, 3).astype(np.float32) / 127.5 - 1.0
        w = np.sqrt(np.maximum(0.0, 1.0 - (xyz ** 2).sum(1)))
        rotations = np.concatenate([xyz, w[:, None]], 1)
    return {"positions": positions, "scales": scales, "rotations": rotations.astype(np.float32),
            "alphas": alphas, "colors": colors, "sh": sh, "sh_degree": sh_degree, "version": version}


def _smallest_three(r: np.ndarray) -> np.ndarray:
    """(N,4) bytes -> (N,4) xyzw. 2 bits: index of the largest component; then 3 x (9-bit magnitude scaled
    by 1/sqrt(2), 1 sign bit), packed from the highest remaining index down."""
    comp = r[:, 0].astype(np.uint32) | (r[:, 1].astype(np.uint32) << 8) | (r[:, 2].astype(np.uint32) << 16) \
        | (r[:, 3].astype(np.uint32) << 24)
    largest = (comp >> 30).astype(np.int64)
    mask = np.uint32((1 << 9) - 1)
    q = np.zeros((len(r), 4), np.float32)
    rest = comp.copy()
    for i in range(3, -1, -1):
        here = largest != i
        mag = (rest & mask).astype(np.float32)
        neg = ((rest >> 9) & 1).astype(bool)
        value = np.float32(np.sqrt(0.5)) * mag / np.float32(mask)
        q[here, i] = np.where(neg, -value, value)[here]
        rest = np.where(here, rest >> 10, rest)
    q[np.arange(len(r)), largest] = np.sqrt(np.maximum(0.0, 1.0 - (q ** 2).sum(1)))
    return q


def to_ply(cloud: dict) -> bytes:
    """Standard 3DGS binary PLY (what splat_render.parse_ply, SuperSplat and the INRIA viewers read).
    f_rest is channel-major as in INRIA's format; rot_0..3 is w, x, y, z."""
    n, dim = len(cloud["positions"]), cloud["sh"].shape[1]
    rot = cloud["rotations"]
    cols = [cloud["positions"], np.zeros((n, 3), np.float32), cloud["colors"],
            cloud["sh"].transpose(0, 2, 1).reshape(n, dim * 3), cloud["alphas"][:, None], cloud["scales"],
            np.concatenate([rot[:, 3:4], rot[:, :3]], 1)]
    names = (["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
             + [f"f_rest_{i}" for i in range(dim * 3)] + ["opacity", "scale_0", "scale_1", "scale_2"]
             + ["rot_0", "rot_1", "rot_2", "rot_3"])
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    header += [f"property float {name}" for name in names] + ["end_header"]
    body = np.ascontiguousarray(np.concatenate(cols, 1), dtype="<f4").tobytes()
    return ("\n".join(header) + "\n").encode("ascii") + body


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
    cloud = decode_spz(spz)

    item = root / scan_id
    tmp = root / f".{scan_id}.partial"  # write fully, then rename: --watch never sees half an item
    (tmp / "reference_views").mkdir(parents=True, exist_ok=True)
    (tmp / "splat.spz").write_bytes(spz)
    (tmp / "splat.ply").write_bytes(to_ply(cloud))
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
                if not (SAMPLES / scan["scan_id"] / "splat.ply").is_file():
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
