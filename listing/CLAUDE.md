# Mint listing pipeline (listing/)

This folder is one lane of the Mint hackathon project. It turns a seller's photos of an item into a priced listing for the website. Other folders in the repo belong to teammates. Read the root CLAUDE.md for team-wide rules; this file covers `listing/` only.

## What the pipeline does

Input: an item folder with `photos/` (the product from several angles, normally 8 JPGs) and optionally `input.json`: `seller_name`, `asking_price_cad`, `photo_urls` (public URLs of the same photos, same order; Lens needs one). The CLI also takes `--seller-name` / `--asking-price`.
Output: `runs/<item>/result.json`: a `Listing` (title, description, condition, price with its sources, deal rating) or a `Rejection` when the photos aren't the product the seller named.

Stages (each starts as soon as its inputs exist):

1. `load_photos` (local): each photo upright from EXIF, shrunk to 1024 px on its long side, saved as JPEG to `runs/<item>/views/p01.jpg`... One size for every later call: Gemini can still read printed text, Jev's 280-1568 px limits hold, and requests stay small.
2. `identify`: photos + seller name -> `Identity`, as specific as the evidence allows. In parallel: one Gemini call reads every photo (printed text, product type, its best guess at brand and model), and Google Lens (Serper, `stages/lens.py`) searches two photos for visually matching products (the photo's `source_url`, else the photo is uploaded to the public Supabase bucket `assets/listing-photos/<item>/`). If the read doesn't settle a model, one text-only Gemini call (fuse) weighs the read, the seller's name and the Lens titles into a candidate. **Code decides what is claimed** (`decide`, `IDENTIFY`): a value is backed when it is printed on the item, in the seller's name, or in at least 3 Lens titles from 2 different sites (whole words: "MX Master 3" isn't backed by "MX Master 3S"). A brand needs one kind of backing, an exact model two (and a backed brand). `product_name` is the most specific backed name ("Logitech MX Master 3S" / "Logitech wireless mouse" / "wireless mouse"), `specificity` says which, `evidence` says what backed it. `search_query` is the name plus the product type, so every search stays within the right kind of product.
3. `baseline_lookup`: seller's name or `Identity.search_query` -> `Baseline` (one clean product photo, Serper image search + Jev photo checks). With a seller name it starts at once, before the photos load.
4. `match_gate`: photos + baseline (+ identity, seller name) -> `MatchCheck` (Jev, one request per photo). Only a seller-typed name is a claim (`has_claim`): a reference photo that looks like a different product then gives a `Rejection`. Without one, the search was ours (identify can be wrong; seen live: "ThinkPad" taken for a model found a ThinkPad laptop), so it's `uncertain`, never a rejection. At least half the photos must be usable.
5. Beside the match check (cancelled if it rejects): `listing_text`, `reference_price`, and `condition`.
   - `listing_text`: `Identity` -> `ListingDraft` (Gemini). When the exact model is known, one Serper web search for it supplies sources (titles and snippets), and the text may state the model's features, but code only lets through specs and model numbers that the sources state. Without an exact model, no specs at all. Never price or condition. Falls back to a template after `TEXT["budget_s"]`.
   - `reference_price`: `Identity` + seller name -> `ReferencePrice`. Real listings first: one Serper shopping search (`gl=ca`) for the seller's name or `search_query`, one flash-lite call checks every result against the item (the exact model when one is backed, else anything in the brand or line that fits) and says which are sold new on their own. Code parses each CAD price, keeps the best `same_product` tier (widening when no model is backed and the top tier is too thin), and takes the median (outliers dropped from 3 listings; 2 must agree within 1.6x). Needs 2 listings from 2 sellers -> `new_retail`, sources in `Listing.price_sources`, normal deal confidence; nothing named means no listings price. Otherwise the estimate chain (ungrounded Gemini estimate, then a category default). Budget `SERPER_PRICE["budget_s"]`.
   - `condition` (Jev): photos + baseline + identity -> `Condition`. The context names the printed text and colours identify read off the item (`jev_questions.design_note`), so logos aren't scratches.
6. `deal_rating`: the asking price (default: the suggested price) against `finalize`'s price -> `DealRating` (pure code). Weak inputs widen the fair price into a range.
7. `finalize`: everything -> `Listing`; the price is computed here in code. Without a baseline photo a defect needs a score of 0.75 (not 0.60) to be noted or priced. Previews are the first 4 photos.
8. `result.json` is written and `run_pipeline`'s `on_listing` hook called (e.g. to post the listing). Every run also writes `runs/<item>/timings.json` (`timing.py`): each stage's wall time split into Gemini, Jev, Serper, download and upload waiting and our own code, plus the critical path.

## Layout

```
listing/
  contracts.py       # Pydantic models. Source of truth for every stage.
  pipeline.py        # run_pipeline(item_dir, seller_name=None) -> Listing | Rejection
  stages/            # one file per stage, named as above; lens.py is identify's Lens helper
  timing.py          # per-run stage timing -> timings.json
  cache.py           # cached stage outputs keyed by item id + stage + inputs
  images.py          # fit images to Jev's limits
  ingest.py          # a finished Supabase scan's 8 views -> samples/<scan_id>/photos/
  samples/           # local items (gitignored, never commit)
  fixtures/          # one folder per test item: stubs, expected JSON
  runs/              # raw outputs of every run (gitignored)
  scripts/           # smoke tests and one-off tools
```

## Commands (Windows PowerShell)

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python pipeline.py fixtures/item01    # must print a valid Listing
python pipeline.py fixtures/item02    # must print a Rejection
python -m pytest
python pipeline.py samples/<item> --asking-price 120   # a live run on a folder with photos/
python ingest.py <scan_id> [--seller-name "..."]      # a Supabase scan's views as an item folder
python scripts/try_identify.py samples/<item>          # identify alone: claim, evidence, Lens titles
python scripts/timing_runs.py samples/<item> --label x # timed live runs, saved for comparison
```

Run the two pipeline checks and the tests after every change. They must still pass before you say a task is done.

## Rules

- `contracts.py` is the source of truth. Don't add, remove or rename fields unless the task asks for it. If a stage needs a change, stop and say so.
- Every stage is an async function: contract objects in, one contract object out. No global state (the timer and Gemini client caches are per run / per event loop).
- Every stage writes its output as JSON to `runs/<item_id>/<stage>.json`. Model stages also save raw answers there (`identify_raw.json` has the read, Lens matches, fuse and what wasn't claimed).
- No product-specific logic: no special cases, brand lists, or prompts or thresholds tuned to particular items.
- If `DEMO_MODE=1`, every stage reads from `cache.py` first and only runs on a cache miss. Cache entries are keyed by a hash of the stage's inputs (upstream outputs, seller name, asking price, the photos' names and sizes, manual-baseline flag), so a changed input is a miss, never a stale hit.
- `DEMO_MODE=offline` (or `--offline`) is a cache-only demo: a miss in a stage that calls an API raises `DemoCacheMiss` naming the stage; pure-code stages (`deal_rating`, `finalize`) still run. Before a demo, run each item once with `DEMO_MODE=1`, then check with `--offline`.
- `--manual-baseline` (or `MANUAL_BASELINE=1`) makes `baseline_lookup` use the item folder's `baseline.jpg/png` and never search. If no usable baseline is found, `match_gate` returns `uncertain` (no Jev call) and `condition` runs the no-baseline questions. With no seller name and only a product type identified, `baseline_lookup` doesn't search at all.
- Thresholds, weights and price factors live in a dict at the top of their stage file. Never inline magic numbers in logic.
- Decisions are made in code from model outputs. Models supply probabilities or structured fields, never the final verdict, claim or price.
- Unit-test decision rules and the price formula with fake inputs. Tests never call a real API (`tests/conftest.py` blocks Gemini, Jev, Serper, Lens and uploads).
- Stay inside `listing/`. Don't edit files elsewhere in the repo, including the root `.gitignore` and root `CLAUDE.md`.
- Keep changes small and focused on the task. Don't refactor unrelated code.

## Keys and secrets

- Keys come from the repo-root `.env` (one file for all of Mint; see `../.env.example`) via `python-dotenv`: `TYPESAFE_API_KEY`, `GEMINI_API_KEY`, `SERPER_API_KEY` (Lens, image search, shopping search, model sources), and `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (only to upload a photo for Lens when the input has no public URL; without them identify goes on without Lens).
- Fail early with a clear message if a key is missing.
- Never print, log, commit or hardcode a key. Never put a key in a fixture or in `runs/`.

## Jev (TypeSafe), verified with typesafe-sdk 0.7.5

- Model name is `jev-latest`. Plain `jev` returns 400 Unknown model.
- Call shape: `async with AsyncTypeSafeClient(model="jev-latest") as c: r = await c.system_one(state=..., questions=..., extra_headers=...)`.
- Images are opt-in: send `extra_headers={"TypeSafe-Danger-Zone-Images": "true"}` on every request that contains an image.
- Images: PNG or JPEG, each side 280 to 1568 px, max 16 MiB each and 32 MiB per request. Out-of-range images are rejected, not resized, and one bad image fails the whole request. EXIF orientation is ignored, so rotate pixels upright first (`load_photos` does).
- Put images in `state` as named fields (`Image(bytes_or_path)`) and refer to them in questions with backticks, e.g. `` `item` ``.
- Question IDs are never sent to the model. The instructions must carry the full meaning.
- Questions in one request run in parallel and can't see each other's answers.
- Read answers with `r.nouls[id].noul`, `r.scores[id].score`, `r.choices[id].choice`.
- One request per photo, all photos concurrently with `asyncio.gather`.
- Aggregate per question across usable photos with the 2nd-highest value, so one noisy photo can't flip a result.
- Allow about +/-0.04 run-to-run noise. Never build logic that flips at exactly 0.5.
- Errors: `TypeSafeError` (base), `TypeSafeBadRequestError` (400), `TypeSafeAuthenticationError` (401), all from `typesafe_sdk`.
- Add a timeout and one retry. Fall back to the cache when demo mode is on.

## Gemini

- Use the `google-genai` SDK; one client per event loop (`gemini_client`), set up while the photos load.
- Every Gemini call (identify's read and fuse, listing_text, reference_price) uses `GEMINI["model"]` in `stages/identify.py`, currently `gemini-3.5-flash-lite`. `GEMINI_MODEL` in the environment is ignored with a warning.
- Search grounding is off (`GEMINI["search_grounding"]`): the free-tier project gets 0 grounding requests a day. Prices come from Serper listings; the model estimate is only the fallback.
- Always pass a response schema built from the matching model in `contracts.py`. Never parse free text.
- `identify` sends all photos in one call. Don't add per-photo Gemini calls. A listing makes 3-4 Gemini calls: identify's read, fuse (only when the read doesn't settle a model), listing_text, the price check (+1 estimate if the listings don't give a price, +1 listing_text retry when its text fails the checks).
- The key belongs to the AI Studio project htv11 (free tier), shared with `gsplat/` and the team: gemini-3.5-flash-lite 15 requests/min, 500/day, reset at midnight Pacific. On a 429 the call waits what Gemini asks (up to `GEMINI["max_retry_wait_s"]`) and retries once. Several listings back to back can hit the per-minute limit; space them out.
- Gemini's brand and model are guesses; only code's `decide` claims them.
- `listing_text` never mentions price or condition.

## Done means

- The pipeline checks and tests pass.
- New behaviour has a test or a fixture that exercises it.
- You've said what you changed, what you didn't do, and anything that needs a human to look at real outputs (photos, Jev scores, prompts).
