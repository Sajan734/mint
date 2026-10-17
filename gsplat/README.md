# gsplat: phone video → clean object splat (role A)

One or two phone orbit videos in, an object-only Gaussian splat plus 8 reference views out, on a Modal GPU.

| Input | Output |
|---|---|
| `top.*` (upright orbit), optional `bottom.*` (same object flipped over), any phone video incl. 60/120 fps | `splat.spz` (~2.5 MB; Spark and `listing/` read it directly), 8 reference views + `views.json` |

The splat is in the **scan frame**: +Y up, +X along the object's long axis, origin on the ground under the object
(its lowest points at y = 0), right-handed (SPZ's native RUB, so viewers need no flip). Scale is **not metric** yet
(VGGT poses).

## Run

```bash
cd gsplat && python -m venv .venv && .venv/Scripts/pip install modal   # once; then `modal setup`
modal run app.py --video orbit.mp4 --gpu H100                            # one video
modal run app.py --video orbit.mp4 --video2 orbit_reverse.mp4 --name merged --gpu H100   # top + bottom
```

Results land in `out/<name>/` (gitignored): `splat.spz`, `views/` (reference views), `run.json` (timings, quality),
and debug media (`masks_*.jpg`, `poses_*.jpg`, `register.jpg`, `heldout.jpg`, `turntable.mp4`). Open `viewer.html`
and pick the `.spz`.

Useful flags: `--gpu H100` (faster), `--scale 1.0` (training resolution; default auto from a pixel budget), `--ply`
(also write a ~35 MB `.ply`, only for inspecting in desktop tools; nothing downstream uses it),
`--no-debug`, `--no-box-refine`, `--stop-after masks|poses|register`, `--train-json '{"iters": 1500}'`.

### Live pipeline: phone video -> website

```
iPhone app --scan-upload Edge Function--> scans/{id}/video.mp4
  --Supabase webhook (supabase_setup/webhook.sql)--> on_upload (Modal endpoint, starts each scan once)
  --> Splatter.run_scan on an H100: splat + 8 views + 24 spin frames  (mintsplat/publish.py)
  --> listing/ pipeline in the same container: render, identify, Jev match + condition, price  (mintsplat/market.py)
  --> assets/listings/index.json  --> the website (buyer/lib/data/live.ts) lists it at /listing/{id}
```

| Where (Supabase, public `assets` bucket unless noted) | What |
|---|---|
| `scans/{id}/video.mp4` (private) | the phone's video (+ `bottom.mp4`, the item flipped over, uploaded first); the app's `poses.jsonl` turns its sideways frames upright |
| `splats/{id}.spz`, `splats/{id}.json` | the splat; manifest (inputs, URLs, views, spin frames, Gaussians, stage timings) |
| `views/{id}/` | 8 reference views (transparent + grey PNG) + `views.json` (cameras) + `spin/f00..f23.webp` |
| `splats/index.json` | every splat, newest first (`listing/ingest.py` reads it) |
| `listings/{id}.json` | `status` listed / rejected / failed, with the website's `MarketListing`, the `Rejection` or the error |
| `listings/{id}/vNN.png`, `listings/index.json` | the listing's preview renders; every listing document inline, newest first |
| Realtime `batch:{id}` | `stage` events (started/done per step, incl. `7_listing`), `passport_ready`, `listing_ready` |

Needs two Modal secrets: `mint-supabase` (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`) and `mint-listing`
(`TYPESAFE_API_KEY`, `GEMINI_API_KEY`, `SERPER_API_KEY`, the keys in `listing/.env`). Fill in the repo-root
`.env` (copy of `../.env.example`, gitignored), run `python push_secrets.py` (checks the Supabase key, writes both secrets, prints only
names), then `modal deploy app.py`. Without `mint-listing` the splat still publishes and the listing step is skipped. Live scans go
on the website under the seller and garage sale in `market.LIVE`; the category comes from the identified product.

```bash
modal deploy app.py                          # prints the on_upload URL that webhook.sql calls
python client.py scan orbit.mp4 orbit_reverse.mp4   # exactly the phone's path (bottom.mp4 first, video.mp4 last);
                                                   # the webhook does the rest; prints the time of each hop
python client.py relist <scan_id> [--title "Lenovo ThinkPad wireless mouse"]   # re-run only the listing step
```

- **Product name:** the title the seller types on the dashboard (`scans/{id}/session.json`, scanner/DASHBOARD.md) goes
  to listing/ as `seller_name`. Without it listing/ only searches for a reference photo when the model is printed on
  the item, so condition is judged from the scan alone and the listing asks for a seller check.
- **Cold start:** `session.json` (scan requested or picked up) and `bottom.mp4` also hit the webhook, which starts
  `Splatter.prewarm` on an H100: models load and one tiny real job warms CUDA while the seller is still recording.
- **Debugging a listing:** each stage's JSON is published to `assets/listings/{id}/run/` (`run_url` in the document),
  also when it fails.
- **Publish:** a listing starts unpublished. The seller's editor calls the `api` endpoint
  (`POST /listings/{id}/publish {state, title, description, price_cad}`, CORS open, the service key stays on Modal),
  which applies their edits and sets `published`; the buyer site shows only published listings.
- **Buyer's rescan check** (`mint://verify?id=<cid>&listing=<scan_id>`): the phone uploads `rescan.capture.json`
  (`listing_scan_id`) and `rescan.mp4` last (+ `rescan2.mp4` flipped). The webhook starts `Splatter.run_verify`: it
  splats the rescan (published as `splats/{cid}`, not indexed), compares like with like (a rescan without an underside
  is compared with the listing's top lap only, cached as `splats/{listing}.top.spz`), and runs the buyer agent
  (`multiagent/buyer_agent`, Jev + Groq, in its own container `compare_scans`, upright alignment) on the two splats.
  Result: `assets/comparisons/{cid}.json` (CompareResponse) + view pairs `assets/comparisons/{cid[:8]}/a_NN.png`.
  Tested: the same mouse -> `same`; another object -> `alignment_failed` ("we could not tell"), by the agent's design.
- **A broken GPU context** (CUDA assert) makes the container exit; Modal retries the scan on a fresh one.

Measured on 2026-10-17, `orbit.mp4` + `orbit_reverse.mp4` (43 MB), H100:

| Path | Upload done | Splat published | Listing published |
|---|---|---|---|
| Cold (no prewarm) | 7.0 s | 65.9 s | 84.9 s |
| Dashboard flow (prewarm from session.json, 30 s recording) | 4.0 s | 42.8 s | 72.7-78.6 s |
| Warm container | 4.0 s | 39.9 s | 56.2 s |

The listing step is 15-35 s of that: listing/'s render (~3-7.5 s) and Gemini identify (~5-19 s, varies).

**Gemini model and quota:** each listing makes ~3 Gemini requests (identify, title/text, price). On the free tier
the Flash models allow 20 a day (~6 listings), then `429 RESOURCE_EXHAUSTED` and the listing is published as `failed`
(the splat is fine). So development runs on `GEMINI_MODEL=gemini-3.5-flash-lite` (500 a day, ~160 listings; tested:
listed in 19 s, but it reads less off the item, e.g. no brand from the ThinkPad logo, so the seller's product title
matters more). **Demo day:** set `GEMINI_MODEL=gemini-3.5-flash` in the root `.env` (or enable billing), then
`python push_secrets.py && modal deploy app.py`. `python client.py relist <scan_id>` redoes a failed listing.

### Demo (no cold start)

```bash
python client.py warm --gpu H100        # keeps one GPU container loaded (billed while warm)
python client.py run orbit.mp4 orbit_reverse.mp4 --gpu H100 --name merged
python client.py cold --gpu H100        # always after the demo
```

## The 8 reference views

On a cube centred on the object, yaw-aligned with it, framed so the object fills ~85% of each 1024 px image:

- **top + bottom captured:** the 8 cube corners (4 upper at +35°, 4 lower at -35°)
- **top only:** 8 points around the cube's top face: its 4 corners (+35°) and the midpoints of its 4 top edges (+45°)

Each view is a transparent PNG (web) and an opaque PNG on the listing pipeline's mid-grey (Jev). `views.json` has
every camera (OpenCV camera-to-world in the scan frame, intrinsics), so anyone can re-render the same viewpoint.

## Pipeline (`mintsplat/`)

| Stage | File | What |
|---|---|---|
| frames | `frames.py` | sharpest frame per time bucket (80 per video); videos decoded in parallel; >30 fps only scores every k-th frame |
| masks | `masks.py` | SAM 2 video propagation from a centre prompt, re-prompted with the grown box so attached parts (stands, casters) are included; only small enclosed holes are filled, real see-through gaps stay open |
| poses | `poses.py` | VGGT on unmasked frames; support plane constrained to be roughly horizontal w.r.t. the cameras' up (walls and box sides rejected), camera up as fallback; yaw along the object's long axis |
| register | `merge.py` | bottom capture → top frame: similarity fit so each video's points stay inside the other's silhouettes |
| train | `train.py` | gsplat MCMC (200k cap), L1 + SSIM, random backgrounds, alpha loss, per-view pose refinement, needle regulariser; training resolution from a 0.5 MP crop budget |
| export | `export.py` | mask-vote cleanup, drop Gaussians invisible in every training view, SPZ v3 (6/5-bit SH) |
| views | `views.py` | the 8 reference views above |
| publish | `publish.py` | storage mode: Supabase in/out, `mint-work`, index |

## Numbers (warm H100, top-only unless noted)

Held-out PSNR is measured inside the object mask on ~10% of frames never trained on, after letting each held-out
camera fit its pose to the splat (training refines poses, so fixed poses would understate quality).

| Object (video) | Time | Held-out PSNR | `.spz` |
|---|---|---|---|
| chair (25 s, 120 fps, thin legs, casters) | ~28 s | 24.8 | 2.6 MB |
| backpack (20 s, people in frame) | ~24 s | 27.2 | 3.0 MB |
| desk phone (20 s, on a box, coiled cord) | ~27 s | 26.8 | 2.3 MB |
| ThinkPad mouse, top + bottom (2 × 23 s) | ~35 s | 29.5 | 2.7 MB |

Known limits: thin dangling parts that SAM 2 includes only sometimes (a phone's coiled cord) reconstruct as wisps;
glossy black surfaces show some mottling; a side the video never saw stays empty.

## Not done yet

Keyframes / `bbox` / `sha256` for the passport contract, metric scale, and the live Supabase test (needs the
`mint-supabase` secret).
