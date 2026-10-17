"""Talk to the DEPLOYED splat app (run `modal deploy app.py` once first).

    python client.py warm [--gpu H100]          # keep 1 GPU container loaded (billed while on)
    python client.py run orbit.mp4 [--name x]   # mp4 -> out/<name>/splat.spz on the warm container
    python client.py run orbit.mp4 orbit_reverse.mp4 --name merged   # top + flipped-over bottom
    python client.py cold [--gpu H100]          # back to scale-to-zero after the demo
    python client.py relist <scan_id> [--title "Lenovo ThinkPad mouse"]   # re-run only the listing step
    python client.py scan orbit.mp4 [orbit_reverse.mp4]
        # the live pipeline end to end, exactly like the iPhone (scanner/HANDOFF.md): the scan-upload Edge Function
        # signs the uploads (no key on the client), bottom.mp4 goes first, video.mp4 last; its arrival fires the
        # Supabase webhook -> run_scan on an H100 -> splat + views -> listing/ (Jev) -> assets/listings/{id}.json,
        # which the website shows. Times each hop and saves everything to out/scan_<id>/.

Use the same --gpu for warm, run and cold: each GPU type is its own pool of containers.
Warm H100: one video ~24-28 s, top + bottom ~35 s (training resolution is set automatically; see README).

`modal run app.py` starts a fresh app every time (always cold); this script reuses the deployed one.
"""
import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import modal

APP, CLS = "mint-gsplat", "Splatter"
SUPABASE_URL = "https://jpanyhsifoxxiizkgjno.supabase.co"  # public project URL, not a secret
PUBLIC = f"{SUPABASE_URL}/storage/v1/object/public/assets"
UPLOAD_FN = f"{SUPABASE_URL}/functions/v1/scan-upload"  # the iOS app's signer (scanner/supabase), needs no key


def save(res: dict, out_dir: Path, wall: float) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, data in res.pop("files").items():
        (out_dir / fname).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / fname).write_bytes(data)
    res["wall_incl_upload_and_cold_start"] = round(wall, 1)
    (out_dir / "run.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    print(f"\nwrote {out_dir}/")


def put(url: str, path: Path) -> float:
    """Upload one file to a signed URL (what the phone does). Returns seconds."""
    t0 = time.perf_counter()
    req = urllib.request.Request(url, data=path.read_bytes(), method="PUT",
                                 headers={"Content-Type": "video/mp4" if path.suffix == ".mp4" else "video/quicktime",
                                          "x-upsert": "true"})
    with urllib.request.urlopen(req, timeout=300) as r:
        r.read()
    return time.perf_counter() - t0


def get_json(url: str) -> dict | None:
    """A public object, never from a cache; None until it exists."""
    try:
        with urllib.request.urlopen(f"{url}?t={time.time_ns()}", timeout=10) as r:
            return json.loads(r.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


def phone_upload(scan_id: str, files: dict[str, Path]) -> None:
    """What the iOS app does: ask the scan-upload Edge Function for signed URLs, then PUT each file in order."""
    body = json.dumps({"scan_id": scan_id, "files": list(files)}).encode()
    req = urllib.request.Request(UPLOAD_FN, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        signed = {u["file"]: u["signed_url"] for u in json.loads(r.read())["uploads"]}
    for name, path in files.items():  # in order: video.mp4 last, its arrival starts the pipeline
        put(signed[name], path)


def scan(videos: list[Path], scan_id: str | None = None, timeout_s: float = 900) -> dict:
    scan_id = scan_id or str(uuid.uuid4())
    t: dict[str, float] = {"upload_mb": sum(p.stat().st_size for p in videos) / 1e6}
    start = time.perf_counter()
    files = {"bottom.mp4": videos[1]} if len(videos) > 1 else {}
    files["video.mp4"] = videos[0]
    phone_upload(scan_id, files)
    t["uploaded_s"] = time.perf_counter() - start
    print(f"scan {scan_id}: uploaded {', '.join(files)} in {t['uploaded_s']:.1f} s; the webhook takes it from here",
          flush=True)

    manifest = listing = None  # watch the public bucket, as the website does
    while time.perf_counter() - start < timeout_s and listing is None:
        time.sleep(1.0)
        if manifest is None and (manifest := get_json(f"{PUBLIC}/splats/{scan_id}.json")):
            t["splat_published_s"] = time.perf_counter() - start
            print(f"  splat published at {t['splat_published_s']:.1f} s", flush=True)
        if (listing := get_json(f"{PUBLIC}/listings/{scan_id}.json")):
            t["listing_published_s"] = time.perf_counter() - start
            print(f"  listing {listing['status']} at {t['listing_published_s']:.1f} s", flush=True)
    return {"scan_id": scan_id, "client_timings": {k: round(v, 2) for k, v in t.items()},
            "website_path": f"/listing/{scan_id}", "manifest": manifest, "listing": listing}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("warm", "cold"):
        sub.add_parser(name).add_argument("--gpu", default="")
    r = sub.add_parser("run")
    r.add_argument("--gpu", default="", help="e.g. H100 (default: the app's L40S)")
    r.add_argument("--scale", type=float, default=0.0, help="training resolution (0 = auto; 1.0 = full res)")
    r.add_argument("video")
    r.add_argument("video2", nargs="?", help="same object flipped over; merged into one splat")
    r.add_argument("--name", default="")
    r.add_argument("--debug", action="store_true", help="also produce eval sheets + turntable")
    r.add_argument("--ply", action="store_true", help="also return the uncompressed .ply")
    s = sub.add_parser("scan")
    s.add_argument("video", help="the main lap (uploaded as video.mp4)")
    s.add_argument("video2", nargs="?", help="the item flipped over (uploaded first, as bottom.mp4)")
    s.add_argument("--scan-id", default=None, help="upload into this scan (e.g. one the dashboard requested)")
    rl = sub.add_parser("relist", help="re-run only the listing step on a published splat")
    rl.add_argument("scan_id")
    rl.add_argument("--title", default=None, help="product name, as the seller would type it")
    args = ap.parse_args()
    if args.cmd == "relist":
        t0 = time.perf_counter()
        doc = modal.Cls.from_name(APP, CLS)().relist.remote(args.scan_id, args.title)
        ml = (doc.get("market_listing") or {}).get("listing") or {}
        print(json.dumps({"status": doc["status"], "error": doc.get("error"), "title": ml.get("title"),
                          "price_cad": ml.get("price_cad"), "needs_seller_check": ml.get("needs_seller_check"),
                          "seller_check_reasons": ml.get("seller_check_reasons"), "run_url": doc.get("run_url"),
                          "timings_ms": doc.get("timings_ms"), "wall_s": round(time.perf_counter() - t0, 1)}, indent=2))
        return
    if args.cmd == "scan":  # no Modal call: the upload alone starts the pipeline, as from the phone
        m = scan([Path(args.video)] + ([Path(args.video2)] if args.video2 else []), args.scan_id)
        out = Path("out") / f"scan_{m['scan_id'][:8]}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "scan.json").write_text(json.dumps(m, indent=2))
        print(json.dumps({k: m[k] for k in ("scan_id", "client_timings", "website_path")}, indent=2))
        if m["manifest"]:
            print("server stage timings (ms):", json.dumps(m["manifest"]["stage_timings_ms"]))
        if m["listing"]:
            print("listing:", m["listing"]["status"], m["listing"].get("error") or "",
                  json.dumps(m["listing"].get("timings_ms", {})))
        print(f"\nsaved to {out}/scan.json")
        return

    cls = modal.Cls.from_name(APP, CLS)
    splatter = (cls.with_options(gpu=args.gpu) if args.gpu else cls)()
    if args.cmd == "warm":
        print(splatter.update_autoscaler(min_containers=1))
        print("Keeping 1 container warm. Give it ~30 s to boot and load models. Run `cold` when done.")
    elif args.cmd == "cold":
        print(splatter.update_autoscaler(min_containers=0))
        print("Scale-to-zero restored (the container idles out after scaledown_window).")
    else:
        src = Path(args.video)
        t0 = time.perf_counter()
        payload = [src.read_bytes(), Path(args.video2).read_bytes()] if args.video2 else src.read_bytes()
        res = splatter.run.remote(payload, {"debug": args.debug, "ply": args.ply,
                                            "train": {"train_scale": args.scale or None}})
        save(res, Path("out") / (args.name or src.stem), time.perf_counter() - t0)


if __name__ == "__main__":
    main()
