# Mint listing pipeline (listing/)

This folder is one lane of the Mint hackathon project. It turns a seller's trained Gaussian splat into a priced listing for the website. Other folders in the repo belong to teammates. Read the root CLAUDE.md for team-wide rules; this file covers `listing/` only.

## What the pipeline does

Input: a trained gsplat of one item, plus an optional product name typed by the seller.
Output: a `Listing`, or a `Rejection` if the scan doesn't match the looked-up product.

Stages, in order:

1. `render`: splat -> 12 PNG views (8 around at 10 degrees, 4 at 40 degrees), 1024x1024, mid-grey background. Rendered locally in plain PyTorch by `splat_render.py` (CUDA if available), which imports nothing from the pipeline so a Modal job can reuse it. Up axis per item via `input.json` `up_axis` or `--up-axis` (default `+y`). Writes `runs/<item>/contact_sheet.png` for checking by eye; `scripts/try_render.py` renders without any API calls.
2. `identify`: views -> `Identity` (Gemini)
3. `baseline_lookup`: seller's name or `Identity.search_query` -> `Baseline` (one clean product photo)
4. `match_gate`: views + baseline -> `MatchCheck` (Jev). On mismatch, return a `Rejection` and stop.
5. In parallel with `asyncio.gather`:
   - `listing_text`: `Identity` -> `ListingDraft` (Gemini)
   - `reference_price` + `condition`: `Identity` -> `ReferencePrice`, views + baseline -> `Condition` (Jev)
6. `finalize`: everything -> `Listing`. The price is computed here in code.

The 3D turntable viewer is out of scope for now. Don't build it unless asked.

## Layout

```
listing/
  contracts.py       # Pydantic models. Source of truth for every stage.
  pipeline.py        # run_pipeline(splat_path, seller_name=None) -> Listing | Rejection
  stages/            # one file per stage, named as above
  cache.py           # cached stage outputs keyed by item id + stage
  splat_render.py    # 3DGS .ply loading, floater-robust framing, PyTorch rasterizer
  images.py          # fit images to Jev's limits
  samples/           # local sample splats (gitignored, never commit)
  fixtures/          # one folder per test item: views, baseline, expected JSON
  runs/              # raw outputs of every run (gitignored)
  scripts/           # smoke tests and one-off tools
  eval.py            # runs every fixture, one line per item
```

## Commands (Windows PowerShell)

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python pipeline.py fixtures/item01    # must print a valid Listing
python pipeline.py fixtures/item02    # must print a Rejection
python -m pytest
python eval.py
```

Run the two pipeline checks and the tests after every change. They must still pass before you say a task is done.

## Rules

- `contracts.py` is the source of truth. Don't add, remove or rename fields unless the task asks for it. If a stage needs a change, stop and say so.
- Every stage is an async function: contract objects in, one contract object out. No global state.
- Every stage writes its output as JSON to `runs/<item_id>/<stage>.json`. Jev stages also save raw per-view answers there.
- If `DEMO_MODE=1`, every stage reads from `cache.py` first and only calls an API on a cache miss.
- `--manual-baseline` (or `MANUAL_BASELINE=1`) makes `baseline_lookup` use the item folder's `baseline.jpg/png` and never search, so demos don't depend on search. If no usable baseline is found, `Baseline.image_path` is null and `match_gate` returns `uncertain` (no Jev call), which flags a seller check. With no seller-typed name and a null `Identity.model`, `baseline_lookup` doesn't search at all (a generic query finds some other product). `condition` then runs the no-baseline questions on the views alone, so pricing still works.
- Thresholds, weights and price factors live in a dict at the top of their stage file. Never inline magic numbers in logic.
- Decisions are made in code from model outputs. Models supply probabilities or structured fields, never the final verdict or price.
- Unit-test decision rules and the price formula with fake inputs. Tests never call a real API.
- Stay inside `listing/`. Don't edit files elsewhere in the repo, including the root `.gitignore` and root `CLAUDE.md`.
- Keep changes small and focused on the task. Don't refactor unrelated code.

## Keys and secrets

- Keys come from `listing/.env` via `python-dotenv`: `TYPESAFE_API_KEY`, `GEMINI_API_KEY`, `SERPER_API_KEY` (image search for `baseline_lookup`).
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
- `identify` sends all 12 views in one call.
- Never invent brand or model. If the images don't support it, return null. Brand must be backed by `visible_text`.
- `listing_text` never mentions price or condition.

## Done means

- The pipeline checks and tests pass.
- New behaviour has a test or a fixture that exercises it.
- You've said what you changed, what you didn't do, and anything that needs a human to look at real outputs (renders, Jev scores, prompts).