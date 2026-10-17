"""After the splat: run the listing pipeline (listing/, Jev + Gemini) on the scan and publish a website-ready
MarketListing (buyer/lib/types.ts) to the public bucket.

  assets/listings/{scan_id}.json      {"v", "scan_id", "status": listed | rejected | failed, "market_listing" |
                                       "rejection" | "error", "timings_ms", ...}
  assets/listings/{scan_id}/vNN.png   the listing pipeline's preview renders (Listing.preview_images point here)
  assets/listings/{scan_id}/run/      each stage's JSON (identify, baseline_lookup, match_gate, condition, ...):
                                       where to look when a listing comes out wrong or fails
  assets/listings/index.json          every scan, newest first, documents inline (one fetch for the website)

A listed scan starts unpublished: the seller reviews the draft and publishes it (set_published, called by the
website through gsplat/app.py `api`), which applies their title, description and price. Buyers see published ones.

listing/ runs unchanged, in-process: the item folder is built the way listing/ingest.py builds it, and the
render stage uses this container's GPU (RENDER_BACKEND=local), so there is no second cold start.
"""
import asyncio
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ASSETS = "assets"
LISTING_DIR = Path(os.environ.get("MINT_LISTING_DIR", "/listing"))

# Where live scans appear on the website until sellers are real: an existing seller and garage sale from
# buyer/mock (the site validates seller_id / garage_sale_id against them). run_scan cfg["market"] overrides.
LIVE = {
    "seller_id": "sel_raj",
    "garage_sale_id": "gs_agincourt_tech",
    "location": {"neighbourhood": "Agincourt", "city": "Toronto"},
}

# Website categories (lib/types.ts Category), matched as word prefixes against the identified category first,
# then the title and tags. First match wins; deterministic, no model.
CATEGORY_WORDS = {
    "electronics": ["electronic", "computer", "mouse", "keyboard", "phone", "headphone", "earbud", "speaker",
                    "camera", "laptop", "tablet", "monitor", "console", "controller", "charger", "cable", "router",
                    "audio", "gadget", "remote", "smartwatch"],
    "furniture": ["furniture", "chair", "table", "desk", "stool", "shelf", "shelv", "sofa", "couch", "cabinet",
                  "dresser", "bench", "lamp"],
    "clothing_accessories": ["clothing", "apparel", "shoe", "sneaker", "boot", "jacket", "shirt", "hat", "bag",
                             "backpack", "purse", "wallet", "sunglass", "jewel", "accessor", "watch"],
    "toys_games": ["toy", "game", "puzzle", "lego", "doll", "plush", "figurine"],
    "books_media": ["book", "novel", "magazine", "dvd", "vinyl", "comic"],
    "sports_outdoors": ["sport", "bike", "bicycle", "racket", "golf", "skate", "camping", "tent", "fitness",
                        "yoga", "helmet", "outdoor"],
    "garden_plants": ["plant", "garden", "planter", "succulent", "flower", "seed"],
    "home_kitchen": ["kitchen", "cook", "pan", "mug", "cup", "plate", "bowl", "kettle", "appliance", "decor",
                     "vase", "home"],
}
DEFAULT_CATEGORY = "home_kitchen"


def category_for(identity: dict, listing: dict | None = None) -> str:
    texts = [identity.get("category") or ""]
    if listing:
        texts.append(" ".join([listing.get("title", ""), *listing.get("tags", [])]))
    for text in texts:
        text = text.lower().replace("_", " ")
        for cat, words in CATEGORY_WORDS.items():
            if any(re.search(rf"\b{re.escape(w)}", text) for w in words):
                return cat
    return DEFAULT_CATEGORY


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # the site sorts listed_at as text


# --- running listing/ ---------------------------------------------------------------------------------


def prepare_item(scan_id: str, spz: bytes, seller_name: str | None = None, root: Path | None = None) -> Path:
    """samples/<scan_id>/ with splat.spz + input.json, as listing/ingest.py writes it."""
    item = (root or LISTING_DIR / "samples") / scan_id
    item.mkdir(parents=True, exist_ok=True)
    (item / "splat.spz").write_bytes(spz)
    (item / "input.json").write_text(json.dumps({"seller_name": seller_name, "up_axis": "+y", "scan_id": scan_id}))
    return item


def run_listing_pipeline(item: Path) -> tuple[dict, str, Path]:
    """-> (result as a dict, "listing" | "rejection", run dir with the per-stage JSON)."""
    os.environ["RENDER_BACKEND"] = "local"  # render on this container's GPU
    if str(LISTING_DIR) not in sys.path:
        sys.path.insert(0, str(LISTING_DIR))
    from pipeline import RUNS_ROOT, run_pipeline  # listing/pipeline.py

    result = asyncio.run(run_pipeline(item, demo_mode=False))
    kind = "rejection" if type(result).__name__ == "Rejection" else "listing"
    return json.loads(result.model_dump_json()), kind, RUNS_ROOT / item.name


def _stage(run_dir: Path, name: str) -> dict:
    path = run_dir / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def market_listing(scan_id: str, listing: dict, run_dir: Path, manifest: dict, preview_urls: list[str],
                   live: dict) -> dict:
    """listing/ Listing + the website's wrapper fields (buyer/lib/schema.ts MarketListingSchema). The scan id
    is the item id, so the website's /listing/<scan_id> page is the scan's page."""
    spin = manifest.get("spin_urls") or []
    previews = preview_urls or spin[::6][:4] or [v["grey_url"] for v in manifest["views"]["items"][:4]]
    return {
        "listing": {**listing, "item_id": scan_id, "preview_images": previews},
        "seller_id": live["seller_id"],
        "garage_sale_id": live["garage_sale_id"],
        "category": category_for(_stage(run_dir, "identify"), listing),
        "location": live["location"],
        "reference_price_cad": listing["price_cad"],  # Mint's fair value for this item in this condition
        "frames": spin or previews,
        "splat_url": manifest.get("splat_url"),
        "usable_view_count": int(_stage(run_dir, "condition").get("usable_view_count", 0)),
        "listed_at": now_iso(),
        "status": "available",
    }


# --- publishing -----------------------------------------------------------------------------------------


def upload_previews(sb, scan_id: str, listing: dict) -> list[str]:
    """Listing.preview_images are paths under listing/; upload the ones that exist, return their public URLs."""
    paths = [p if Path(p).is_absolute() else LISTING_DIR / p for p in map(Path, listing.get("preview_images", []))]
    paths = [p for p in paths if p.is_file()]
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(lambda p: sb.upload(ASSETS, f"listings/{scan_id}/{p.name}", p.read_bytes(),
                                               "image/png"), paths))


def upload_run(sb, scan_id: str, run_dir: Path) -> list[str]:
    """The listing pipeline's per-stage JSON (whatever stages ran, also after a failure). Returns the file names."""
    files = sorted(run_dir.glob("*.json")) if run_dir.is_dir() else []
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda p: sb.upload(ASSETS, f"listings/{scan_id}/run/{p.name}", p.read_bytes(), "application/json"),
                    files))
    return [p.name for p in files]


def put_doc(sb, scan_id: str, doc: dict) -> dict:
    sb.upload(ASSETS, f"listings/{scan_id}.json", json.dumps(doc, indent=1).encode(), "application/json",
              cache_control="no-cache")
    refresh_listing_index(sb, fresh={scan_id: doc})
    return doc


def set_published(sb, scan_id: str, published: bool, title: str, description: str, price_cad: int) -> dict:
    """The seller's Publish (or Save draft): their title, description and price go into the listing; `published`
    decides whether buyers see it. The pipeline's own price stays as suggested_price_cad and reference_price_cad
    (the fair value the buyer's price badge compares against)."""
    doc = json.loads(sb.download(ASSETS, f"listings/{scan_id}.json"))
    ml = doc.get("market_listing")
    if doc.get("status") != "listed" or not ml:
        raise ValueError(f"scan {scan_id} has no listing to publish (status {doc.get('status')!r})")
    listing = ml["listing"]
    doc.setdefault("suggested_price_cad", listing["price_cad"])
    listing.update(title=title, description=description, price_cad=price_cad)
    if published and not doc.get("published"):
        doc["published_at"] = now_iso()
        ml["listed_at"] = doc["published_at"]  # buyers sort by this: newly published goes first
    doc["published"] = published
    doc["updated_at"] = now_iso()
    return put_doc(sb, scan_id, doc)


def refresh_listing_index(sb, fresh: dict[str, dict] | None = None) -> dict:
    """Rebuild listings/index.json from the folder (not read-modify-write, so scans finishing together can't drop
    each other), documents inline so the website needs one request. no-cache, so it is never served stale.
    `fresh` = documents just written ({scan_id: doc}): used as they are, because reading an object straight after
    overwriting it can still return the old copy (seen: a just-published listing indexed as unpublished)."""
    fresh = fresh or {}
    objs = [o for o in sb.list_objects(ASSETS, "listings") if o["name"].endswith(".json") and o["name"] != "index.json"]

    def doc_for(o: dict) -> dict:
        sid = o["name"].removesuffix(".json")
        return fresh[sid] if sid in fresh else json.loads(sb.download(ASSETS, f"listings/{o['name']}"))

    with ThreadPoolExecutor(8) as ex:
        docs = list(ex.map(doc_for, objs))
    index = {"v": 3, "updated_at": now_iso(), "scans": docs}  # objs are newest first
    sb.upload(ASSETS, "listings/index.json", json.dumps(index).encode(), "application/json", cache_control="no-cache")
    return index


def list_scan(sb, scan_id: str, manifest: dict, spz: bytes, cfg: dict | None = None) -> dict:
    """Run listing/ on a published scan and publish the outcome. Never raises: the splat is already out, so a
    failure here is recorded (status "failed") instead of failing the whole scan."""
    cfg = cfg or {}
    t0 = time.perf_counter()
    doc = {"v": 3, "scan_id": scan_id, "batch_id": manifest.get("batch_id"), "splat_url": manifest.get("splat_url"),
           "spin_urls": manifest.get("spin_urls", []), "seller_name": cfg.get("seller_name"), "created_at": now_iso(),
           "published": False}
    run_dir = LISTING_DIR / "runs" / scan_id  # listing/pipeline.py RUNS_ROOT / item id
    try:
        item = prepare_item(scan_id, spz, cfg.get("seller_name"))
        result, kind, run_dir = run_listing_pipeline(item)
        doc["timings_ms"] = {"listing_pipeline": int((time.perf_counter() - t0) * 1000)}
        if kind == "rejection":
            doc.update(status="rejected", rejection=result)
        else:
            urls = upload_previews(sb, scan_id, result)
            doc.update(status="listed", market_listing=market_listing(scan_id, result, run_dir, manifest, urls,
                                                                      {**LIVE, **cfg.get("market", {})}))
    except Exception as e:  # noqa: BLE001 - recorded and reported, see docstring
        doc.update(status="failed", error=f"{type(e).__name__}: {e}"[:500],
                   timings_ms={"listing_pipeline": int((time.perf_counter() - t0) * 1000)})
    try:
        doc["run_files"] = upload_run(sb, scan_id, run_dir)
        doc["run_url"] = sb.public_url(ASSETS, f"listings/{scan_id}/run/")
    except Exception as e:  # noqa: BLE001 - debugging aid only
        doc["run_files"], doc["run_error"] = [], str(e)[:200]
    return put_doc(sb, scan_id, doc)
