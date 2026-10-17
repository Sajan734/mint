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

### Storage mode (the real flow)

The iOS app uploads `scans/{scan_id}/top.mp4` (+ `bottom.mp4`) with signed URLs, then `mint-api` calls
`Splatter.run_scan.spawn(scan_id)`. That reads the videos from Supabase and publishes (see `mintsplat/publish.py`):

| Where | What |
|---|---|
| `assets/splats/{scan_id}.spz` | the splat |
| `assets/splats/{scan_id}.json` | manifest: inputs, URLs, layout of the views, Gaussian count, per-stage timings |
| `assets/views/{scan_id}/` | 8 reference views (transparent PNG + grey PNG each) + `views.json` (cameras) |
| `assets/splats/index.json` | every published scan, newest first (`listing/ingest.py` polls it, no key needed) |
| Realtime `batch:{id}` | `stage` events (started/done per step), then `passport_ready` with the manifest |

Needs the Modal secret `mint-supabase` (see `supabase_setup/README.md`); create it, then `modal deploy app.py`.
Without it everything else still works and `run_scan` says what's missing.

```bash
modal deploy ../supabase_setup/modal_app.py && modal deploy app.py
python client.py scan orbit.mp4 orbit_reverse.mp4 --gpu H100   # like the phone: signed upload -> run_scan
```

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
