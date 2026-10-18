# listing/ breakdown

What the listing pipeline does, how to run it, and how to build on its output. For the rules of working inside this folder, see [CLAUDE.md](CLAUDE.md).

## What it does

**Input:** an item folder with `photos/` (the product from several angles, normally 8 JPGs), plus an optional `input.json`:

```json
{"seller_name": "Logitech MX Master 3S", "asking_price_cad": 90, "photo_urls": ["https://.../p1.jpg", "..."]}
```

`photo_urls` are public URLs of the same photos, in the same order. Google Lens needs one. Without them the pipeline uploads two photos to the public Supabase bucket itself (`assets/listing-photos/<item>/`, needs `SUPABASE_SERVICE_ROLE_KEY`).

**Output:** `runs/<item>/result.json`, which is either a **Listing** (title, description, condition, price with the listings it came from, deal rating) or a **Rejection** (the photos aren't the product the seller named).

```
load_photos ─► identify ─┬─► baseline_lookup ─► match_gate ─┬─► (mismatch, seller-named) Rejection
  (local)    [read ∥ Lens]│                  └─► condition ──┤
             (+ fuse)     ├─► listing_text (+ model sources) ┤
                          └─► reference_price ───────────────┴─► deal_rating ─► finalize ─► result.json
```

| Stage | What it does | Calls |
|---|---|---|
| `load_photos` | photos upright, shrunk to 1024 px, saved as JPEG (one size serves every model) | none (local) |
| `identify` | what the product is: brand and model when the evidence agrees, else brand and type, else type | 1–2 Gemini + 2 Lens |
| `baseline_lookup` | one clean product photo of it, to compare against | Serper images + Jev photo checks |
| `match_gate` | are the photos that product? Only a seller-typed name can lead to a rejection | 8 Jev (one per photo) |
| `condition` | grade (like new … heavy wear) and defects; printed logos count as design, not damage | 8 Jev |
| `listing_text` | title, description, tags; with an exact model, real features from sources about it | 1 Gemini (+1 Serper search) |
| `reference_price` | new price in CAD from real Canadian listings of that model (or of the brand's line, flagged), median of ≥2 from ≥2 sellers; else an estimate | Serper shopping + 1 Gemini |
| `deal_rating` | asking price vs what the item is worth in its condition | pure code |
| `finalize` | assembles the Listing; the price is computed here in code | pure code |

### How identification decides what to claim

Gemini reads the photos (printed text, product type, its best guess at brand and model) while Google Lens finds visually matching products. If the read alone doesn't settle a model, one more Gemini call weighs the read, the seller's name and the Lens titles. **Code then decides what's claimed:**

- A value is **backed** when it's printed on the item, in the seller's name, or in at least 3 Lens titles from 2 different sites (whole words only: "MX Master 3" isn't backed by "MX Master 3S").
- A **brand** needs one kind of backing. An exact **model** needs two kinds plus a backed brand, and must be more than one plain word (a single word like "ThinkPad" is usually a product line).
- `product_name` is the most specific backed name ("Logitech MX Master 3S" / "Sony wireless headphones" / "plush toy"). `specificity` says which, and `evidence` says what backed it.

Nothing is tuned to particular products.

### What every run writes to `runs/<item>/`

- `result.json`: the Listing or Rejection (what gets posted)
- `<stage>.json` and `*_raw.json`: each stage's output and raw API answers. `identify_raw.json` has the read, the Lens matches, the fuse answer and what wasn't claimed, and why.
- `timings.json`: each stage's wall time split into Gemini, Jev, Serper, download and upload waiting versus our own code, the time to result.json, and the critical path. Typical: **8–10 s** to result.json.

## How to work with it

### Run it

From `listing/`, on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python pipeline.py fixtures/item01                      # offline fixture -> Listing
python pipeline.py fixtures/item02                      # offline fixture -> Rejection
python pipeline.py samples/<item> [--asking-price 30]   # live, on any folder with photos/
python ingest.py <scan_id> [--seller-name "..."]        # a Supabase scan's 8 views as an item folder
python scripts/try_identify.py samples/<item>           # identification alone, with its evidence
python -m pytest                                         # never calls a real API
```

You need these keys in the repo-root `.env`: `GEMINI_API_KEY`, `TYPESAFE_API_KEY`, `SERPER_API_KEY`, and optionally `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (for photos without public URLs).

The Gemini key is shared and free-tier: **15 requests a minute, 500 a day**, at about 4 per listing. Space listings out, and use the cache when you aren't testing a live change:

- `DEMO_MODE=1` reads every stage from `demo_cache/` first, keyed by its inputs.
- `DEMO_MODE=offline` (or `--offline`) never calls an API.

### Read its output

`result.json` (a `Listing` in `contracts.py`):

| Field | Meaning |
|---|---|
| `title`, `description`, `tags`, `attributes` | listing text; names the exact model and its real features only when identify backed that model |
| `condition_grade`, `condition_notes` | `like_new` / `light_wear` / `moderate_wear` / `heavy_wear`, plus buyer-facing notes ("Photo 3 shows a scuff.") |
| `price_cad`, `price_justification` | Mint's price for the item in its condition, and the one-sentence maths behind it |
| `price_sources` | the real listings the new price came from (empty when it's an estimate) |
| `deal_rating` | `great` / `good` / `fair` / `high` / `overpriced` for the asking price, with `confidence` and the reasons |
| `needs_seller_check`, `seller_check_reasons` | what the seller should confirm before publishing |
| `preview_images` | the first 4 photos (resized) |

A `Rejection` has `match_check` with a seller-facing `reason`. The identification itself (`product_name`, `specificity`, `evidence`) is in `runs/<item>/identify.json`.

From Python, `run_pipeline(item_dir, on_listing=hook)` (`pipeline.py`) returns the result; `on_listing` gets it the moment `result.json` is written.

### How it reaches the website

`gsplat/mintsplat/market.py` runs this pipeline in-process after each scan and publishes `assets/listings/{scan_id}.json`. **It still passes a splat**, so it needs a small change before it works with this version. Once the app uploads the 8 photos, `market.prepare_item` should write them to `<item>/photos/` with their public URLs as `photo_urls` in `input.json`, and stop setting `RENDER_BACKEND`. The site reads the `Listing` dict as-is.

### If you change something here

- Stay inside `listing/`, and keep `contracts.py` as the source of truth.
- Thresholds and weights live in a dict at the top of their stage file. No product-specific rules.
- Run the tests and both fixtures before pushing.
