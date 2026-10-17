"""Talk to the DEPLOYED splat app (run `modal deploy app.py` once first).

    python client.py warm [--gpu H100]          # keep 1 GPU container loaded (billed while on)
    python client.py run orbit.mp4 [--name x]   # mp4 -> out/<name>/splat.spz on the warm container
    python client.py run orbit.mp4 orbit_reverse.mp4 --name merged   # top + flipped-over bottom
    python client.py cold [--gpu H100]          # back to scale-to-zero after the demo

Use the same --gpu for warm, run and cold: each GPU type is its own pool of containers.
Merged run (80 frames per video), warm: L40S ~36 s; H100 ~29 s; H100 --scale 1.0 ~37 s (sharpest).

`modal run app.py` starts a fresh app every time (always cold); this script reuses the deployed one.
"""
import argparse
import json
import time
from pathlib import Path

import modal

APP, CLS = "mint-gsplat", "Splatter"


def save(res: dict, out_dir: Path, wall: float) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, data in res.pop("files").items():
        (out_dir / fname).write_bytes(data)
    res["wall_incl_upload_and_cold_start"] = round(wall, 1)
    (out_dir / "run.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    print(f"\nwrote {out_dir}/")


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
    args = ap.parse_args()

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
                                            "train": {"train_scale": args.scale}})
        save(res, Path("out") / (args.name or src.stem), time.perf_counter() - t0)


if __name__ == "__main__":
    main()
