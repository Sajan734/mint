# gsplat: phone video → clean object splat (role A)

One or two phone videos of an item in, an item-only Gaussian splat plus 8 held-out photos out, on a Modal H100.

| Videos recorded | Coverage | What viewers may do |
|---|---|---|
| 1 (the upright lap) | `top`: the underside was never filmed | orbit the **top half** only: `splat_url` ends in `#maxpolar=90`, which the website's viewer reads (`lib/splat-scene.ts` `fragmentMaxPolar`) |
| 2 (upright lap, then the item flipped over: `bottom.mp4`) | `full` | orbit the **whole sphere** |

The iPhone app can record more passes (`pass3.mp4`, ...); only the first two are used.

The splat is in the **scan frame**: +Y up, +X along the item's long axis, origin on the ground under the item,
right-handed (SPZ's native RUB, so viewers need no flip). Scale is **not metric** yet (VGGT poses).

## Outputs

| File | What |
|---|---|
| `splat.spz` | the splat (~2.5 MB); Spark and `listing/` read it directly |
| `heldout/00.jpg` … `07.jpg` + `heldout.json` | 8 **real video frames** of the item, for the agents to find the exact product online (identify, Google Lens via Serper): masked to the item's outline (convex hull: everything inside it is kept, e.g. the mouse's red button), on white, 768 px square. One video: one every 45° around the item. Two videos: 6 around the top + 2 of the underside (labels, model stickers). In each direction the **sharpest frame with the item biggest and fully in view, from a product-photo angle** wins. They are **held out of training**, so the splat never saw them. `heldout.json`: pass, video frame, camera angles, score |
| `spin/f00.webp` … `f23.webp` | the website's drag-to-spin frames |
| `run.json` | timings, coverage, frame counts, pose and cleanup stats (`--debug`: + held-out PSNR) |

`--debug` also writes `masks_*.jpg`, `poses_*.jpg` and `register.jpg` contact sheets. Nothing else is written:
no turntable videos, no rendered reference views, no `.ply` unless asked (`--ply`; only the buyer agent's
comparison needs one).

## Run locally against Modal

```bash
cd gsplat && python -m venv .venv && .venv/Scripts/pip install modal   # once; then `modal setup`
modal run app.py --video orbit.mp4                                       # one video -> runs/orbit/
modal run app.py --video orbit.mp4 --video2 orbit_reverse.mp4 --name merged   # top + bottom
```

Results land in `runs/<name>/` (gitignored). Open `viewer.html` and pick the `.spz`. Flags: `--scale 1.0`
(training resolution; default auto), `--ply`, `--no-debug`, `--no-box-refine`, `--stop-after masks|poses|register`,
`--train-json '{"iters": 1500}'`, `--gpu A100` (a different GPU type to compare; its own pool, always cold).

`out/` holds frozen runs from the first pipeline that the buyer app's demo reads (`buyer/scripts/make_demo_assets.py`,
`buyer/e2e-demo`); leave it alone. `legacy/` (gitignored) holds old experiments, test videos and turntables.

## Warm and cold containers (Modal)

Every GPU job (webhook scans, buyer rescans, `client.py`, `modal run`) runs in **one pool**: class `Splatter` on
an H100, app `mint-gsplat`. A container in it is either cold (not running) or warm (running with SAM 2 and VGGT
loaded).

| | Cold | Warm |
|---|---|---|
| What happens on a scan | Modal boots a container, loads the models (~25-30 s), then runs the scan | the scan starts at once |
| Phone upload → splat published (orbit pair, 2026-10-17) | ~66 s | ~40 s |
| Cost | nothing while idle | the H100's per-second price **for every second it is up**, busy or not |

**Defaults (no action needed):** containers scale to zero. After a job a container stays warm for **5 minutes**
(`scaledown_window=300`), so back-to-back scans are warm. When the dashboard starts a scan (`session.json`) or the
phone uploads `bottom.mp4`, the webhook calls `Splatter.prewarm`, so the cold start mostly happens while the
seller is still recording. A container whose GPU breaks (CUDA assert) exits and Modal retries the scan on a fresh
one.

**Keep one warm (demo, recording, judging):**

```bash
python client.py warm      # min_containers=1: one H100 always up (billed continuously)
python client.py status    # "containers up: 1" once it has booted (~30-60 s); or `modal container list`
python client.py run orbit.mp4 --name warmup   # optional: one throwaway run warms CUDA and the caches too
...
python client.py cold      # ALWAYS afterwards: back to scale-to-zero (it shuts down after 5 idle minutes)
```

- **`modal deploy app.py` resets it**: run `warm` again after every deploy.
- Warm only the pool you use. There is just one now, so `warm` covers the webhook too.
- Several scans at once each get their own container; only the first is warm.
- Check the bill at modal.com → Usage. A forgotten `warm` is the expensive mistake: run `cold`.
- The CPU functions (`on_upload`, `api`, `compare_scans`) start in ~1-3 s and never need warming.

## Live pipeline: phone video -> website

```
iPhone app --scan-upload Edge Function--> scans/{id}/bottom.mp4 (optional), then video.mp4
  --Supabase webhook (supabase_setup/webhook.sql)--> on_upload (Modal endpoint, starts each scan once)
  --> Splatter.run_scan: splat + 8 held-out photos + 24 spin frames  (mintsplat/publish.py)
  --> listing/ pipeline in the same container, on the 8 held-out photos: identify (Gemini + Google Lens on their
      public URLs), Jev match + condition, price  (mintsplat/market.py)
  --> assets/listings/index.json  --> the website (buyer/lib/data/live.ts) lists it at /listing/{id} once published
```

| Where (Supabase, public `assets` bucket unless noted) | What |
|---|---|
| `scans/{id}/` (private) | the phone's `video.mp4` (+ `bottom.mp4`, the item flipped over, uploaded first), `poses.jsonl` (turns its sideways frames upright), `session.json` (the dashboard's product title) |
| `splats/{id}.spz`, `splats/{id}.json` | the splat; manifest: `coverage`, `passes`, `orbit.max_polar_deg`, `splat_url` (with the fragment), `heldout.items[]` (url + angles), `spin_urls`, stage timings |
| `heldout/{id}/` | `00.jpg` … `07.jpg` + `heldout.json` |
| `spin/{id}/` | `f00.webp` … `f23.webp` |
| `splats/index.json` | every splat, newest first (`listing/ingest.py` reads it) |
| `listings/{id}.json` | `status` listed / rejected / failed, `published`, `coverage`, `heldout_urls`, the website's `MarketListing` |
| `listings/{id}/vNN.png`, `listings/{id}/run/*.json`, `listings/index.json` | preview renders; each listing stage's JSON (debugging); every listing document inline |
| Realtime `batch:{id}` | `stage` events (incl. `7_listing`), `passport_ready`, `listing_ready` |

The listing step gets the held-out photos as its item's `photos/` and their public URLs as `input.json`
`photo_urls` (Google Lens needs them); `listing/ingest.py` builds the same item folder from a published scan.

Needs three Modal secrets, written from the repo-root `.env` by `python push_secrets.py`: `mint-supabase`,
`mint-listing` (Jev, Gemini, Serper) and `mint-buyer` (the buyer agent). Then `modal deploy app.py`.

```bash
modal deploy app.py                                  # prints the on_upload + api URLs
python client.py scan orbit.mp4 orbit_reverse.mp4    # exactly the phone's path; times each hop
python client.py relist <scan_id> --title "Lenovo ThinkPad Essential Wireless Mouse"   # redo only the listing
python client.py rescan <scan_id> [...]              # redo splat + photos + listing for scans already uploaded
```

- **Product name:** the title the seller types on the dashboard (`session.json`) goes to listing/ as
  `seller_name`, which finds real prices for that exact model (Serper shopping).
- **Publish:** a listing starts unpublished. The seller's editor calls the `api` endpoint
  (`POST /listings/{id}/publish {state, title, description, price_cad}`; 404 unknown scan, 409 not publishable,
  502 storage hiccup: press Publish again). The buyer site shows only published listings.
- **Buyer's rescan check** (`mint://verify?id=<cid>&listing=<scan_id>`): the phone uploads `rescan.capture.json`
  and `rescan.mp4` last. `Splatter.run_verify` splats it, compares like with like (a rescan without an underside
  is compared with the listing's top lap, cached as `splats/{listing}.top.spz`) and runs the buyer agent
  (`multiagent/buyer_agent`, its own container `compare_scans`, upright alignment) -> `assets/comparisons/{cid}.json`
  (CompareResponse; the per-view pairs feed Jev but aren't published). If the alignment is trusted (ok, not
  misaligned, ambiguity <= 0.85) the rescan's `splat_url` also gets `ry=<deg>` in its fragment, the B->A yaw of the
  aligner's matrix (`mintsplat/yaw.py`), so the viewer shows both scans in one orientation.
- **Gemini quota:** development runs on `GEMINI_MODEL=gemini-3.5-flash-lite` (500 requests a day). Demo day:
  `gemini-3.5-flash` in the root `.env`, then `python push_secrets.py && modal deploy app.py` (and `warm` again).

**Supabase backup:** `python supabase_setup/backup.py` copies every bucket into `supabase_clear/` (gitignored) and
checks each file's size. Run it before deleting anything.

## Pipeline (`mintsplat/`)

| Stage | File | What |
|---|---|---|
| frames | `frames.py` | sharpest frame per time bucket (80 per video), turned upright from the app's poses |
| masks | `masks.py` | SAM 2 video propagation from a centre prompt, re-prompted with the grown box so attached parts are included; the mask is the item's **outline** (its convex hull), with everything inside kept, so parts SAM 2 drops (the mouse's red button) stay in the splat |
| poses | `poses.py` | VGGT on the frames; support plane roughly horizontal w.r.t. the cameras' up; yaw along the long axis |
| heldout | `heldout.py` | the 8 held-out photos (above), chosen per pass |
| register | `merge.py` | bottom capture → top frame: similarity fit so each video's points stay inside the other's silhouettes |
| train | `train.py` | gsplat MCMC (200k cap), L1 + SSIM, random backgrounds, alpha loss, per-view pose refinement, needle regulariser; the held-out photos' frames are never trained on |
| export | `export.py` | mask-vote cleanup, drop Gaussians invisible in every training view, SPZ v3 |
| spin | `spin.py` | the 24 spin frames |
| publish | `publish.py` | Supabase in/out, manifest, index |

## Numbers (warm H100, orbit videos of the ThinkPad mouse, 2026-10-17)

Held-out PSNR is measured inside the item mask on the 8 held-out frames, after letting each held-out camera fit
its pose to the splat.

| Videos | GPU time | Held-out PSNR | `.spz` |
|---|---|---|---|
| 1 (top) | 27 s | 30.0 | ~2.6 MB |
| 2 (top + bottom) | 35 s | 29.0 | ~2.7 MB |

Known limits: thin dangling parts that SAM 2 includes only sometimes (a coiled cord) reconstruct as wisps;
glossy black surfaces show some mottling; a side the video never saw stays empty (hence `#maxpolar=90`).
