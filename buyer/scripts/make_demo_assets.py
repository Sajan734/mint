"""Build the real demo assets for the mock mode. Idempotent: run it again and every output is rewritten.

    multiagent\\.venv\\Scripts\\python.exe -I buyer\\scripts\\make_demo_assets.py [scans] [listing] [compare] [paslcd]
    python3 -I buyer/scripts/make_demo_assets.py listing        (one step; no names = every step)

Writes (all from real files, nothing invented):
  buyer/public/demo/scans/{name}/views/NN.webp       8 reference views of each gsplat/out scan (transparent, 640 px)
  buyer/public/demo/scans/live_check/spin/fNN.webp   the 24 spin frames, copied as they are
  buyer/public/demo/scans/{name}/photos/pN.webp      the REAL photo tiles of heldout.jpg (see HELDOUT below)
  buyer/public/demo/scans/index.json                 what exists, per scan
  seller/mock/real-scans.json                        the 5 scans as "scanned, listing not written yet" rows
  buyer/public/demo/listings/{scan8}/                a real end-to-end listing (gsplat/out/scan_{scan8}/listing.json):
                                                     its .spz, preview images and spin frames, fetched from Supabase,
                                                     and listing.json with only the URLs pointed at these copies
  seller/mock/scan-result.json                       that listing's market_listing: what demo mode's scan flow replays
  buyer/mock/compare/{run8}.json                     byte copies of multiagent/runs/<run>/response.json
  buyer/public/local/{pots,zen}/fNN.webp             rebuilt by make_paslcd_frames.py when its inputs exist
"""
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

from PIL import Image

BUYER = Path(__file__).resolve().parent.parent
ROOT = BUYER.parent
SCANS_SRC = Path(os.environ.get("GSPLAT_OUT", ROOT / "gsplat" / "out"))  # GSPLAT_OUT: a checkout of gsplat/out elsewhere
SCANS_OUT = BUYER / "public" / "demo" / "scans"
LISTINGS_OUT = BUYER / "public" / "demo" / "listings"
RUNS = ROOT / "multiagent" / "runs"
# A real run end to end: phone upload -> splat -> listing agent, a ThinkPad mouse (gsplat/out/scan_a6816dfc/scan.json).
LISTING_SCAN = "a6816dfc"
SOURCE = "gsplat/out (real scan, commit e80f994)"

# scan folder -> plain object name (confirmed on the images and in gsplat/README.md) and a note that tells twins apart
SCANS = {
    "backpack": ("backpack", None),
    "chair": ("office chair", None),
    "phone": ("desk phone", None),
    "merged": ("ThinkPad mouse", "Top and bottom scan"),
    "live_check": ("ThinkPad mouse", "Top scan, with spin frames"),
}
COMPARE_RUNS = ["435e1251", "fc4b95cb", "cce6fb01"]

# HELDOUT: gsplat/mintsplat/pipeline.py builds the sheet as
#   debug.sheet([g for g, _ in pairs] + [r for _, r in pairs], cols=len(pairs))
# where train.evaluate() returns pairs of (gt, render): gt = the captured frame times the object mask, render = the
# splat. With cols=4, row 0 is the 4 real photos (black background = masked out) and row 1 the 4 splat renders.
# sheet() uses 360 px tiles, so the crop below needs no resizing.
HELDOUT_COLS, HELDOUT_ROWS = 4, 2


def webp(im: Image.Image, path: Path, max_side: int, quality: int) -> None:
    im = im.copy()
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=quality)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def build_scans() -> None:
    shutil.rmtree(SCANS_OUT, ignore_errors=True)
    index, rows = [], []
    for name, (obj, note) in SCANS.items():
        src, out = SCANS_SRC / name, SCANS_OUT / name
        url = f"/demo/scans/{name}"
        views = sorted(p for p in (src / "views").glob("[0-9][0-9]_az*_el*.png") if not p.stem.endswith("_grey"))
        if len(views) != 8:
            raise SystemExit(f"{name}: expected 8 reference views, found {len(views)}")
        for p in views:
            webp(Image.open(p), out / "views" / f"{p.name[:2]}.webp", 640, 82)
        spin = sorted((src / "views" / "spin").glob("f*.webp"))
        for p in spin:
            (out / "spin").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, out / "spin" / p.name)
        photos = []
        if (src / "heldout.jpg").exists():
            sheet = Image.open(src / "heldout.jpg").convert("RGB")
            tw, th = sheet.width // HELDOUT_COLS, sheet.height // HELDOUT_ROWS
            for i in range(HELDOUT_COLS):
                webp(sheet.crop((i * tw, 0, (i + 1) * tw, th)), out / "photos" / f"p{i + 1}.webp", 640, 82)
                photos.append(f"{url}/photos/p{i + 1}.webp")
        files = {
            "views": [f"{url}/views/{p.name[:2]}.webp" for p in views],
            "spin": [f"{url}/spin/{p.name}" for p in spin],
            "photos": photos,
        }
        index.append({"name": name, "object": obj, "files": files, "source": SOURCE, "splat_url": None})
        rows.append({
            "id": f"scan_{name}", "name": obj[0].upper() + obj[1:], **({"note": note} if note else {}),
            "images": files["views"], "photos": photos, "spin_frames": files["spin"],
            "splat_url": None, "state": "scanned", "source": SOURCE,
        })
    write_json(SCANS_OUT / "index.json", index)
    write_json(ROOT / "seller" / "mock" / "real-scans.json", rows)


def tls() -> ssl.SSLContext:
    # python.org's macOS build ships no CA certificates; certifi's bundle fixes that when it is installed.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def build_listing() -> None:
    """Copy one real listing's files next to the site, so demo mode shows the real scan and works offline.

    Only URLs change. Every word, price and flag is the listing agent's, as published.
    """
    doc = json.loads((SCANS_SRC / f"scan_{LISTING_SCAN}" / "listing.json").read_text(encoding="utf-8"))
    out, url = LISTINGS_OUT / LISTING_SCAN, f"/demo/listings/{LISTING_SCAN}"
    shutil.rmtree(out, ignore_errors=True)
    local: dict[str, str] = {}
    ctx = tls()

    def fetch(src: str, rel: str) -> str:
        if src not in local:
            path = out / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(src, timeout=60, context=ctx) as r:
                data = r.read()
            if path.suffix == ".webp" and not src.endswith(".webp"):
                path.write_bytes(data)
                webp(Image.open(path).convert("RGB"), path, 1024, 82)
            else:
                path.write_bytes(data)
            local[src] = f"{url}/{rel}"
        return local[src]

    m = doc["market_listing"]
    l = m["listing"]
    doc["splat_url"] = m["splat_url"] = fetch(m["splat_url"], "splat.spz")
    m["frames"] = [fetch(u, f"spin/{u.rsplit('/', 1)[1]}") for u in m["frames"]]
    doc["spin_urls"] = [fetch(u, f"spin/{u.rsplit('/', 1)[1]}") for u in doc["spin_urls"]]
    l["preview_images"] = [fetch(u, f"previews/{Path(u).stem}.webp") for u in l["preview_images"]]
    write_json(out / "listing.json", doc)
    write_json(ROOT / "seller" / "mock" / "scan-result.json", m)


def build_compare() -> None:
    for run8 in COMPARE_RUNS:
        run = next(RUNS.glob(f"{run8}*"), None)
        if run is None or not (run / "response.json").exists():
            raise SystemExit(f"run {run8} not found under {RUNS}")
        (BUYER / "mock" / "compare").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run / "response.json", BUYER / "mock" / "compare" / f"{run8}.json")


def build_paslcd() -> None:
    done = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("make_paslcd_frames.py"))])
    if done.returncode:
        print("WARNING: make_paslcd_frames.py failed (its PASLCD inputs are missing?); public/local/{pots,zen} not rebuilt")


STEPS = {"scans": build_scans, "listing": build_listing, "compare": build_compare, "paslcd": build_paslcd}

if __name__ == "__main__":
    names = sys.argv[1:] or list(STEPS)
    unknown = [n for n in names if n not in STEPS]
    if unknown:
        raise SystemExit(f"unknown step(s) {unknown}; choose from {list(STEPS)}")
    for n in names:
        STEPS[n]()
    print("done")
