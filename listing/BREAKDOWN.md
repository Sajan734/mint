# listing/ breakdown

What the listing pipeline does today, what's about to change, and how to build on it now. For the rules of working inside this folder, see [CLAUDE.md](CLAUDE.md).

## What it does today

Input: one item folder holding a trained Gaussian splat (`splat.spz` or `splat.ply`) and an optional `input.json` (`seller_name`, `asking_price_cad`, `up_axis`).
Output: `runs/<item>/result.json`, which is either a **Listing** (title, description, condition, price, deal rating) or a **Rejection** (the scan isn't the product the seller named).

```
render ─► identify ─┬─► baseline_lookup ─► match_gate ──┬─► (mismatch) Rejection
                    │                  └─► condition ───┤
                    ├─► listing_text ───────────────────┤
                    └─► reference_price ────────────────┴─► deal_rating ─► finalize ─► result.json
                                          (condition) ─► highlight (background, rewrites result.json)
```

| Stage | What it does | Calls |
|---|---|---|
| `render` | 12 views of the splat (8 around, 4 from above), 1024 px | Modal GPU or local GPU |
| `identify` | category, brand and model, but only text actually read off the item counts | 1 Gemini call |
| `baseline_lookup` | one clean product photo of the named product, to compare against | Serper image search + Jev photo checks |
| `match_gate` | is the scan the product named? Only a seller-typed name or a printed model can make it a rejection | 12 Jev calls |
| `condition` | grade (like new … heavy wear) and defects, with printed logos treated as design, not damage | 12 Jev calls |
| `listing_text` | title, description, tags; falls back to a template if Gemini fails or is slow | 1 Gemini call |
| `reference_price` | new price in CAD from real listings (Serper shopping, Canada), filtered by Gemini, median of at least 2 listings from 2 sellers; otherwise a model estimate, then a category default | Serper + 1 Gemini call |
| `deal_rating` | asking price vs what the item is worth in its condition | pure code |
| `finalize` | assembles the Listing; the price is computed here in code | pure code |
| `highlight` | a copy of the splat with defects tinted red | Gemini + GPU (**being removed**) |

The decisions are always made in code. The models only supply probabilities and fields.

Every run writes these to `runs/<item>/`:
- `result.json`: the Listing or Rejection (what gets posted)
- `<stage>.json`, plus `*_raw.json` with each stage's raw API answers
- `timings.json`: each stage's wall time split into Gemini, Jev, Serper and download waiting versus our own code, the time to result.json, and the critical path

### Recent changes on this branch

- **Real prices.** `reference_price` uses real Canadian listings instead of a Gemini guess, and records them in `Listing.price_sources` (title, seller, price, link), so the site can show where a price came from. Deal ratings backed by real listings are normal confidence.
- **Fewer false "uncertain" matches.** When identify read "ThinkPad" but not a model, the reference photo search used to be skipped. Four ThinkPad mouse scans in Supabase went from uncertain to match. Rejections still happen, but only when the seller typed a name or a model is printed on the item.
- **Faster and bounded.** Stages start as soon as their inputs exist, and slow Gemini or Serper calls fall back instead of stalling the listing. Each run's timings are saved in `timings.json`.

## What's going to change

These are planned, not built yet:

1. **The input becomes a JPG, not a splat.** We'll receive one JPG showing the product from several angles. `render` and all GPU work (Modal and local) leave the pipeline, and the views come from the JPG instead.
2. **The highlighted splat is cancelled.** A teammate has a better alternative. The `highlight` stage, `Listing.highlight` and its files will be removed. Condition stays, because it drives the price and the description.
3. **Identification gets much better, and stays honest.**
   - Planned evidence sources: Google Lens matches through Serper (it needs a public image URL; our Supabase bucket is public), the text read off the item, and the seller's name. Possibly a stronger Gemini model for identify alone.
   - An exact model is claimed only when the evidence agrees; otherwise the pipeline gives the most specific product it can support (e.g. "Logitech wireless mouse"), never just "black mouse".
   - A confidence for the identification will be recorded.
4. **The listing follows from the model.**
   - Titles that name the product the way a real listing does.
   - Descriptions with that exact model's real features plus the honest condition.
   - Prices from listings of that exact model, not the whole product line.
5. **Measured, not assumed.** A small ground-truth set (items we have photos of, plus the Supabase scans we know) will score identification and price before and after.

Expect `contracts.py` to change: the input contract changes, `highlight` disappears from `Listing`, and an identification confidence is added. Anything that reads `result.json` should treat the fields below as the stable core.

## How to work off what's here now

### Run it

From `listing/`, on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python pipeline.py fixtures/item01                      # offline fixture -> Listing
python pipeline.py fixtures/item02                      # offline fixture -> Rejection
python ingest.py <scan_id> [--seller-name "..."]        # download a finished scan from Supabase into samples/<scan_id>
python pipeline.py samples/<scan_id> [--asking-price 30]   # live run on it
python -m pytest                                         # 448 tests, never call a real API
```

You need these keys in the repo-root `.env`: `GEMINI_API_KEY`, `TYPESAFE_API_KEY`, `SERPER_API_KEY`, and `RENDER_BACKEND` (`modal` or `local`, until rendering goes away). The Gemini key is shared and its quota is small (one listing makes about 3 calls), so use the cache when you aren't testing a live change:

- `DEMO_MODE=1` reads every stage from `demo_cache/` first, keyed by its inputs, and caches what it computes.
- `DEMO_MODE=offline` (or `--offline`) never calls an API: a missing cache entry is an error naming the stage.

### Read its output

`result.json` (a `Listing` in `contracts.py`). These fields are safe to build on:

| Field | Meaning |
|---|---|
| `title`, `description`, `tags`, `attributes` | listing text (will get more specific once identification improves) |
| `condition_grade`, `condition_notes` | `like_new` / `light_wear` / `moderate_wear` / `heavy_wear`, plus buyer-facing notes |
| `price_cad`, `price_justification` | Mint's price for the item in its condition, and the one-sentence maths behind it |
| `price_sources` | the real listings the new price came from (empty when it's an estimate) |
| `deal_rating` | `great` / `good` / `fair` / `high` / `overpriced` for the asking price, with `confidence` and the reasons |
| `needs_seller_check`, `seller_check_reasons` | what the seller should confirm before publishing |
| `highlight` | **going away**; don't build on it |

A `Rejection` has `match_check` with a seller-facing `reason`.

From Python, `run_pipeline(item_dir, on_listing=hook)` (`pipeline.py`) returns the finished result. `on_listing` gets it as soon as the listing is ready, which is how a caller can post early.

### How it reaches the website

`gsplat/app.py` runs this pipeline in-process after each scan (`gsplat/mintsplat/market.py`) and publishes `assets/listings/{scan_id}.json` plus each stage's JSON under `listings/{scan_id}/run/`. The whole `Listing` dict goes into the site document, so new fields such as `price_sources` reach the site without a code change. **Production only picks up this branch once mint-gsplat is redeployed.**

### Useful scripts

- `scripts/match_before_after.py [scan_id ...]`: Supabase's recorded match and price vs this code, per listing. It only reads from Supabase.
- `scripts/timing_runs.py samples/<scan_id> --label x --runs 2`: timed live runs, saved for comparison.
- `scripts/try_identify.py`, `try_baseline.py`, `try_condition.py`, `try_listing.py`: run one stage live.
- `scripts/replay_match_gate.py`: re-apply match thresholds to saved Jev answers, with no API calls.

### If you change something here

- Stay inside `listing/`. If you need a change in a stage, keep `contracts.py` as the source of truth.
- Thresholds and weights live in a dict at the top of their stage file.
- Run the tests and both fixtures before pushing.
