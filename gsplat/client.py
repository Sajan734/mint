"""Talk to the DEPLOYED splat app (run `modal deploy app.py` once first).

    python client.py warm [--gpu H100]          # keep 1 GPU container loaded (billed while on)
    python client.py run orbit.mp4 [--name x]   # mp4 -> out/<name>/splat.spz on the warm container
    python client.py run orbit.mp4 orbit_reverse.mp4 --name merged   # top + flipped-over bottom
    python client.py cold [--gpu H100]          # back to scale-to-zero after the demo
    python client.py scan orbit.mp4 [orbit_reverse.mp4] [--gpu H100]
        # end-to-end through Supabase, like the phone: signed upload URLs (no key on the client) ->
        # PUT videos -> run_scan(scan_id) -> .spz + 8 cube views + manifest in Storage, events on Realtime

Use the same --gpu for warm, run and cold: each GPU type is its own pool of containers.
Merged run (80 frames per video), warm: L40S ~36 s; H100 ~29 s; H100 --scale 1.0 ~37 s (sharpest).

`modal run app.py` starts a fresh app every time (always cold); this script reuses the deployed one.
"""
import argparse
import json
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import modal

APP, CLS = "mint-gsplat", "Splatter"


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


def scan(splatter, videos: list[Path], scale: float) -> dict:
    scan_id = str(uuid.uuid4())
    names = [f"{role}{p.suffix.lower()}" for role, p in zip(("top", "bottom"), videos)]
    t: dict[str, float] = {}

    t0 = time.perf_counter()
    urls = modal.Function.from_name("mint-supabase", "sign_uploads").remote(scan_id, names)  # supabase_setup/
    t["sign_urls_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    with ThreadPoolExecutor(len(videos)) as ex:  # both videos in parallel, as the app would
        list(ex.map(lambda nv: put(urls[nv[0]], nv[1]), zip(names, videos)))
    t["upload_s"] = time.perf_counter() - t0
    t["upload_mb"] = sum(p.stat().st_size for p in videos) / 1e6

    t0 = time.perf_counter()
    manifest = splatter.run_scan.remote(scan_id, None, {"train": {"train_scale": scale}})
    t["run_scan_wall_s"] = time.perf_counter() - t0
    manifest["client_timings"] = {k: round(v, 2) for k, v in t.items()}
    return manifest


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("warm", "cold"):
        sub.add_parser(name).add_argument("--gpu", default="")
    r = sub.add_parser("run")
    r.add_argument("--gpu", default="", help="e.g. H100 (default: the app's L40S)")
    r.add_argument("--scale", type=float, default=0.75, help="training resolution; 1.0 = sharpest, slower")
    r.add_argument("video")
    r.add_argument("video2", nargs="?", help="same object flipped over; merged into one splat")
    r.add_argument("--name", default="")
    r.add_argument("--debug", action="store_true", help="also produce eval sheets + turntable")
    r.add_argument("--ply", action="store_true", help="also return the uncompressed .ply")
    s = sub.add_parser("scan")
    s.add_argument("video")
    s.add_argument("video2", nargs="?")
    s.add_argument("--gpu", default="")
    s.add_argument("--scale", type=float, default=0.75)
    args = ap.parse_args()

    cls = modal.Cls.from_name(APP, CLS)
    splatter = (cls.with_options(gpu=args.gpu) if args.gpu else cls)()
    if args.cmd == "warm":
        print(splatter.update_autoscaler(min_containers=1))
        print("Keeping 1 container warm. Give it ~30 s to boot and load models. Run `cold` when done.")
    elif args.cmd == "cold":
        print(splatter.update_autoscaler(min_containers=0))
        print("Scale-to-zero restored (the container idles out after scaledown_window).")
    elif args.cmd == "scan":
        videos = [Path(args.video)] + ([Path(args.video2)] if args.video2 else [])
        m = scan(splatter, videos, args.scale)
        out = Path("out") / f"scan_{m['scan_id'][:8]}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text(json.dumps(m, indent=2))
        print(json.dumps(m, indent=2))
        print(f"\nmanifest saved to {out}/manifest.json")
    else:
        src = Path(args.video)
        t0 = time.perf_counter()
        payload = [src.read_bytes(), Path(args.video2).read_bytes()] if args.video2 else src.read_bytes()
        res = splatter.run.remote(payload, {"debug": args.debug, "ply": args.ply,
                                            "train": {"train_scale": args.scale}})
        save(res, Path("out") / (args.name or src.stem), time.perf_counter() - t0)


if __name__ == "__main__":
    main()
