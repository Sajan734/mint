# Mint listing pipeline (listing/)

This folder is one lane of the Mint hackathon project. It turns a seller's trained Gaussian splat into a priced listing for the website. Other folders in the repo belong to teammates. Read the root CLAUDE.md for team-wide rules; this file covers `listing/` only.

## What the pipeline does

Input: a trained gsplat of one item, plus an optional product name and asking price from the seller (`input.json` `seller_name` / `asking_price_cad`, or `--seller-name` / `--asking-price`).
Output: a `Listing` (with a deal rating and a highlighted copy of the splat, when one could be made), or a `Rejection` if the scan doesn't match the looked-up product.

Stages, in order:

1. `render`: splat -> 12 PNG views (8 around at 10 degrees, 4 at 40 degrees), 1024x1024, mid-grey background. Rendered in plain PyTorch by `splat_render.py`, which imports nothing from the pipeline. `RENDER_BACKEND` in the root `.env` picks where: `modal` (default; the deployed `modal_render.py` app on an L4, the .spz or .ply up as bytes, PNGs back as bytes, no warm containers) or `local` (this machine, CUDA if available). Up axis per item via `input.json` `up_axis` or `--up-axis` (default `+y`). Writes `runs/<item>/contact_sheet.png` for checking by eye; `scripts/try_render.py` renders without any Gemini or Jev calls.
2. `identify`: views -> `Identity` (Gemini)
3. `baseline_lookup`: seller's name or `Identity.search_query` -> `Baseline` (one clean product photo)
4. `match_gate`: views + baseline -> `MatchCheck` (Jev). On mismatch, return a `Rejection` and stop.
5. In parallel with `asyncio.gather`:
   - `listing_text`: `Identity` -> `ListingDraft` (Gemini)
   - `reference_price`: `Identity` -> `ReferencePrice`
   - `condition` (Jev): views + baseline + identity -> `Condition`. The Jev context names the printed text and colours `identify` read off the item (`jev_questions.design_note`), so lettering and logos aren't judged as scratches or stains.
   - `highlight` starts as a background task as soon as `condition` is done: splat + views + baseline + identity + condition -> `Highlight` and `runs/<item>/splat_highlighted.<spz|ply>`, a byte copy of the seller's splat with the noted defects tinted red. One Gemini call boxes the marks in every view `condition` flagged, and the item's own printed text and logos; code drops marks that sit on that printing. `splat_render.lift_masks` (on `RENDER_BACKEND`, same cameras as `render`) finds the Gaussians that show inside each box and lie on the visible surface; code keeps boxes the other views confirm (without a baseline photo, every box needs a second view) and the Gaussians the views agree on, and skips the output (saying why) if the marks would cover too much of the item. Isolated: any error becomes status `failed` with the reason, never a failed listing. Check it by eye in `runs/<item>/highlight_sheet.png`; `scripts/try_highlight.py` reruns it alone on a finished run.
6. `deal_rating`: the asking price (default: the suggested price) against `finalize`'s price for the item in its condition -> `DealRating` (pure code). Weak inputs (estimated new price, uncertain match, no baseline, seller check) widen the fair price into a range, and great/good or high/overpriced must hold across it.
7. `finalize`: everything -> `Listing`. The price is computed here in code. Without a baseline photo a defect needs a score of 0.75 (not 0.60) to be noted, priced or highlighted.
8. `result.json` is written (and `run_pipeline`'s `on_listing` hook called, e.g. to post the listing) as soon as the listing is ready. If the highlight is still running its status is `pending`; `finalize` reruns and `result.json` is rewritten when it finishes. `run_pipeline` returns the finished result.

The 3D turntable viewer is out of scope for now. Don't build it unless asked.

## Layout

```
listing/
  contracts.py       # Pydantic models. Source of truth for every stage.
  pipeline.py        # run_pipeline(splat_path, seller_name=None) -> Listing | Rejection
  stages/            # one file per stage, named as above
  cache.py           # cached stage outputs keyed by item id + stage
  splat_render.py    # 3DGS .ply / .spz loading, floater-robust framing, PyTorch rasterizer, mask lifting, tinting
  modal_render.py    # Modal app wrapping splat_render on a GPU (RENDER_BACKEND=modal): render_splat, lift_splat_masks
  images.py          # fit images to Jev's limits
  samples/           # local sample splats (gitignored, never commit)
  fixtures/          # one folder per test item: views, baseline, expected JSON
  runs/              # raw outputs of every run (gitignored)
  scripts/           # smoke tests and one-off tools
```

## Commands (Windows PowerShell)

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
modal deploy modal_render.py          # after any change to splat_render.py or modal_render.py
python pipeline.py fixtures/item01    # must print a valid Listing
python pipeline.py fixtures/item02    # must print a Rejection
python -m pytest
python pipeline.py fixtures/item01 --asking-price 120          # deal rating for a seller's asking price
python scripts/try_highlight.py samples/<scan_id> [--min-score 0.5]   # highlight alone on a finished run
```

Run the two pipeline checks and the tests after every change. They must still pass before you say a task is done.

## Rules

- `contracts.py` is the source of truth. Don't add, remove or rename fields unless the task asks for it. If a stage needs a change, stop and say so.
- Every stage is an async function: contract objects in, one contract object out. No global state.
- Every stage writes its output as JSON to `runs/<item_id>/<stage>.json`. Jev stages also save raw per-view answers there.
- If `DEMO_MODE=1`, every stage reads from `cache.py` first and only runs on a cache miss. Cache entries are keyed by a hash of the stage's inputs (upstream outputs, seller name, asking price, up axis, manual-baseline flag), so a changed input is a miss, never a stale hit. The highlighted splat and debug sheet are cached with the highlight and put back if `runs/` was cleaned. A failed `highlight` is never cached.
- `DEMO_MODE=offline` (or `--offline`) is a cache-only demo: a miss in a stage that calls an API or a GPU raises `DemoCacheMiss` naming the stage; pure-code stages (`deal_rating`, `finalize`) still run, so a new asking price works offline. Before a demo, run each item once with `DEMO_MODE=1`, then check with `--offline`.
- `--manual-baseline` (or `MANUAL_BASELINE=1`) makes `baseline_lookup` use the item folder's `baseline.jpg/png` and never search, so demos don't depend on search. If no usable baseline is found, `Baseline.image_path` is null and `match_gate` returns `uncertain` (no Jev call), which flags a seller check. With no seller-typed name and a null `Identity.model`, `baseline_lookup` doesn't search at all (a generic query finds some other product). `condition` then runs the no-baseline questions on the views alone, so pricing still works.
- Thresholds, weights and price factors live in a dict at the top of their stage file. Never inline magic numbers in logic.
- Decisions are made in code from model outputs. Models supply probabilities or structured fields, never the final verdict or price.
- Unit-test decision rules and the price formula with fake inputs. Tests never call a real API.
- Stay inside `listing/`. Don't edit files elsewhere in the repo, including the root `.gitignore` and root `CLAUDE.md`.
- Keep changes small and focused on the task. Don't refactor unrelated code.

## Keys and secrets

- Keys come from the repo-root `.env` (one file for all of Mint; see `../.env.example`) via `python-dotenv`: `TYPESAFE_API_KEY`, `GEMINI_API_KEY`, `SERPER_API_KEY` (image search for `baseline_lookup`). Also `RENDER_BACKEND` (`modal` or `local`, not a secret). Modal itself uses the login from `modal setup`, not a key in `.env`.
- Fail early with a clear message if a key is missing.
- Never print, log, commit or hardcode a key. Never put a key in a fixture or in `runs/`.

## Jev (TypeSafe), verified with typesafe-sdk 0.7.5

- Model name is `jev-latest`. Plain `jev` returns 400 Unknown model.
- Call shape: `async with AsyncTypeSafeClient(model="jev-latest") as c: r = await c.system_one(state=..., questions=..., extra_headers=...)`.
- Images are opt-in: send `extra_headers={"TypeSafe-Danger-Zone-Images": "true"}` on every request that contains an image.
- Images: PNG or JPEG, each side 280 to 1568 px, max 16 MiB each and 32 MiB per request. Out-of-range images are rejected, not resized, and one bad image fails the whole request. EXIF orientation is ignored, so rotate pixels upright first.
- Put images in `state` as named fields (`Image(bytes_or_path)`) and refer to them in questions with backticks, e.g. `` `item` ``.
- Question IDs are never sent to the model. The instructions must carry the full meaning.
- Questions in one request run in parallel and can't see each other's answers.
- Read answers with `r.nouls[id].noul`, `r.scores[id].score`, `r.choices[id].choice`.
- One request per view, all views concurrently with `asyncio.gather`.
- Aggregate per question across usable views with the 2nd-highest value, so one noisy view can't flip a result.
- Allow about +/-0.04 run-to-run noise. Never build logic that flips at exactly 0.5.
- Errors: `TypeSafeError` (base), `TypeSafeBadRequestError` (400), `TypeSafeAuthenticationError` (401), all from `typesafe_sdk`.
- Add a timeout and one retry. Fall back to the cache when demo mode is on.

## Gemini

- Use the `google-genai` SDK.
- Always pass a response schema built from the matching model in `contracts.py`. Never parse free text.
- `identify` sends all 12 views in one call. `highlight` sends every flagged view in one call too: the team key is on the free tier (20 requests per model per project per day, shared with the live scan pipeline in `gsplat/`), so don't add per-view Gemini calls. A listing makes 3 Gemini calls (identify, listing_text, reference_price), plus 1 for the highlight when a defect is noted, plus up to 2 fallbacks (listing_text retry, ungrounded price).
- Never invent brand or model. If the images don't support it, return null. Brand must be backed by `visible_text`.
- `listing_text` never mentions price or condition.

## Done means

- The pipeline checks and tests pass.
- New behaviour has a test or a fixture that exercises it.
- You've said what you changed, what you didn't do, and anything that needs a human to look at real outputs (renders, Jev scores, prompts).