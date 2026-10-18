"""Talk to the DEPLOYED splat app (`modal deploy app.py` first). Warm and cold containers: README.md.

    python client.py warm                       # keep 1 H100 loaded: no cold start (billed every second it is on)
    python client.py status                     # is a container up?
    python client.py cold                       # back to scale-to-zero (always after a demo)
    python client.py run orbit.mp4 [--name x]   # mp4 -> runs/<name>/ (splat.spz, heldout/, spin/, run.json)
    python client.py run orbit.mp4 orbit_reverse.mp4 --name merged   # top + flipped-over bottom
    python client.py relist <scan_id> [--title "Lenovo ThinkPad mouse"]   # re-run only the listing step
    python client.py rescan <scan_id> [...]     # re-run the whole live pipeline on scans already in Supabase
    python client.py scan orbit.mp4 [orbit_reverse.mp4]
        # the live pipeline end to end, exactly like the iPhone (scanner/HANDOFF.md): the scan-upload Edge Function
        # signs the uploads (no key on the client), bottom.mp4 goes first, video.mp4 last; its arrival fires the
        # Supabase webhook -> run_scan -> splat + held-out photos + spin -> listing/ (Jev) -> assets/listings/{id}.json,
        # which the website shows. Times each hop and saves everything to runs/scan_<id>/.
    python client.py urls                       # after a deploy: the website's API URL into .env + the webhook SQL

Everything (the webhook's scans too) runs in one H100 pool, so `warm` covers all of it. Warm H100: one video
~24-28 s, top + bottom ~35 s (training resolution is set automatically; see README).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root: shared `supabase_setup` package
from supabase_setup.env import load_env, set_env

load_env()  # repo-root .env: MODAL_TOKEN_ID / MODAL_TOKEN_SECRET pick the workspace

APP, CLS = "mint-gsplat", "Splatter"
WEBHOOK_SQL = Path(__file__).resolve().parent.parent / "supabase_setup" / "webhook.sql"
WEBHOOK_URL_SLOT = "<on_upload URL: python gsplat/client.py urls>"
SUPABASE_URL = "https://jpanyhsifoxxiizkgjno.supabase.co"  # public project URL, not a secret
PUBLIC = f"{SUPABASE_URL}/storage/v1/object/public/assets"
UPLOAD_FN = f"{SUPABASE_URL}/functions/v1/scan-upload"  # the iOS app's signer (scanner/supabase), needs no key
CONTENT_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".json": "application/json",
                 ".jsonl": "application/x-ndjson", ".jpg": "image/jpeg"}


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
                                 headers={"Content-Type": CONTENT_TYPES.get(path.suffix.lower(), "video/quicktime"),
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


def urls() -> None:
    """The deployed endpoints of the workspace the .env token is for. The website's `api` URL goes into .env;
    the webhook SQL is printed with `on_upload` filled in, to run once in Supabase after changing workspace."""
    api = modal.Function.from_name(APP, "api").get_web_url()
    on_upload = modal.Function.from_name(APP, "on_upload").get_web_url()
    changed = set_env("NEXT_PUBLIC_MINT_API_URL", api)
    print(f"api        {api}\n           .env NEXT_PUBLIC_MINT_API_URL "
          f"{'updated: restart the web apps' if changed else 'already set'}")
    print(f"on_upload  {on_upload}\n           new workspace? run this once in the Supabase SQL editor:\n")
    print(WEBHOOK_SQL.read_text(encoding="utf-8").replace(WEBHOOK_URL_SLOT, on_upload))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("warm", "cold", "status", "urls"):
        sub.add_parser(name)
    r = sub.add_parser("run")
    r.add_argument("--scale", type=float, default=0.0, help="training resolution (0 = auto; 1.0 = full res)")
    r.add_argument("video")
    r.add_argument("video2", nargs="?", help="same object flipped over; merged into one splat")
    r.add_argument("--name", default="")
    r.add_argument("--debug", action="store_true", help="also the masks/poses contact sheets + held-out PSNR")
    r.add_argument("--ply", action="store_true", help="also return the uncompressed .ply")
    rs = sub.add_parser("rescan", help="re-run splat + listing on scans already in Supabase (overwrites them)")
    rs.add_argument("scan_ids", nargs="+")
    rs.add_argument("--no-listing", action="store_true", help="only the splat, held-out photos and spin")
    s = sub.add_parser("scan")
    s.add_argument("video", help="the main lap (uploaded as video.mp4)")
    s.add_argument("video2", nargs="?", help="the item flipped over (uploaded first, as bottom.mp4)")
    s.add_argument("--scan-id", default=None, help="upload into this scan (e.g. one the dashboard requested)")
    rl = sub.add_parser("relist", help="re-run only the listing step on a published splat")
    rl.add_argument("scan_id")
    rl.add_argument("--title", default=None, help="product name, as the seller would type it")
    args = ap.parse_args()
    if args.cmd == "urls":
        urls()
        return
    if args.cmd == "relist":
        t0 = time.perf_counter()
        doc = modal.Cls.from_name(APP, CLS)().relist.remote(args.scan_id, args.title)
        ml = (doc.get("market_listing") or {}).get("listing") or {}
        print(json.dumps({"status": doc["status"], "error": doc.get("error"), "title": ml.get("title"),
                          "price_cad": ml.get("price_cad"), "needs_seller_check": ml.get("needs_seller_check"),
                          "seller_check_reasons": ml.get("seller_check_reasons"), "run_url": doc.get("run_url"),
                          "timings_ms": doc.get("timings_ms"), "wall_s": round(time.perf_counter() - t0, 1)}, indent=2))
        return
    if args.cmd == "rescan":  # all at once: each gets its own container (up to the app's GPU limit)
        splatter = modal.Cls.from_name(APP, CLS)()
        t0 = time.perf_counter()
        calls = {sid: splatter.run_scan.spawn(sid, None, {"listing": not args.no_listing}) for sid in args.scan_ids}
        for sid, call in calls.items():
            m = call.get()
            doc = m.get("listing") or {}
            ml = (doc.get("market_listing") or {}).get("listing") or {}
            print(json.dumps({"scan_id": sid, "error": m.get("error"), "coverage": m.get("coverage"),
                              "heldout": len((m.get("heldout") or {}).get("items", [])),
                              "listing": doc.get("status"), "title": ml.get("title"), "price_cad": ml.get("price_cad"),
                              "wall_s": round(time.perf_counter() - t0, 1)}))
        return
    if args.cmd == "scan":  # no Modal call: the upload alone starts the pipeline, as from the phone
        m = scan([Path(args.video)] + ([Path(args.video2)] if args.video2 else []), args.scan_id)
        out = Path("runs") / f"scan_{m['scan_id'][:8]}"
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

    splatter = modal.Cls.from_name(APP, CLS)()
    if args.cmd == "warm":
        splatter.update_autoscaler(min_containers=1)
        print("Keeping 1 H100 warm (billed while on). It boots and loads its models in ~30-60 s; `status` shows when "
              "it is up. A redeploy resets this: run `warm` again after every `modal deploy`. Run `cold` when done.")
    elif args.cmd == "cold":
        splatter.update_autoscaler(min_containers=0)
        print("Scale-to-zero restored: the container shuts down after 5 idle minutes (scaledown_window).")
    elif args.cmd == "status":
        try:
            s = splatter.run_scan.get_current_stats()
            print(f"containers up: {s.num_total_runners}, scans waiting: {s.backlog}")
        except Exception as e:  # noqa: BLE001 - older SDKs: the CLI shows the same
            print(f"({type(e).__name__}) use `modal container list` to see running containers")
    else:
        src = Path(args.video)
        t0 = time.perf_counter()
        payload = [src.read_bytes(), Path(args.video2).read_bytes()] if args.video2 else src.read_bytes()
        res = splatter.run.remote(payload, {"debug": args.debug, "ply": args.ply,
                                            "train": {"train_scale": args.scale or None}})
        save(res, Path("runs") / (args.name or src.stem), time.perf_counter() - t0)


if __name__ == "__main__":
    main()
