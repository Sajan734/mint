# gsplat: phone video → clean object splat (role A)

One or two phone orbit videos in, an object-only Gaussian splat out, on a Modal GPU.

| Input | Output |
|---|---|
| `top.mp4` (upright orbit), optional `bottom.mp4` (same object flipped over) | `splat.spz` (~3 MB, Spark-ready), optional `splat.ply` (~39 MB, full precision) |

The splat is in the **scan frame**: +Y up, origin on the support plane under the object, right-handed (SPZ's native RUB, so viewers need no flip). Scale is **not metric** yet (VGGT poses).

## Run

```bash
cd gsplat && python -m venv .venv && .venv/Scripts/pip install modal   # once; then `modal setup`
modal run app.py --video orbit.mp4                                       # one video
modal run app.py --video orbit.mp4 --video2 orbit_reverse.mp4 --name merged   # top + bottom
```

Results land in `out/<name>/` (gitignored): `splat.spz`, `run.json` (timings, quality), and debug media
(`masks_*.jpg`, `poses_*.jpg`, `register.jpg`, `heldout.jpg`, `turntable.mp4`). Open `viewer.html` and pick the `.spz`.

Useful flags: `--gpu H100` (faster), `--scale 1.0` (full-res training, sharpest), `--ply`, `--no-debug`,
`--stop-after masks|poses|register`.

### Demo (no cold start)

```bash
modal deploy app.py
python client.py warm --gpu H100        # keeps one GPU container loaded (billed while warm)
python client.py run orbit.mp4 orbit_reverse.mp4 --gpu H100 --name merged
python client.py cold --gpu H100        # always after the demo
```

## Pipeline (`mintsplat/`)

| Stage | File | What |
|---|---|---|
| frames | `frames.py` | sharpest frame per time bucket (80 per video), videos decoded in parallel |
| masks | `masks.py` | SAM 2 video propagation from a centre prompt, outline only (holes filled) |
| poses | `poses.py` | VGGT on unmasked frames; RANSAC table plane → +Y up, origin under the object |
| register | `merge.py` | bottom capture → top frame: similarity fit so each video's points stay inside the other's silhouettes |
| train | `train.py` | gsplat MCMC (200k cap), L1 + SSIM, random backgrounds, alpha loss, per-view pose refinement |
| export | `export.py` | mask-vote cleanup, SPZ v3 (6/5-bit SH), optional PLY |

## Numbers (ThinkPad mouse, top + bottom, warm container)

| GPU | Time | Held-out PSNR (in mask) | `.spz` |
|---|---|---|---|
| L40S | ~36 s | 26.96 | 2.95 MB |
| H100 | ~29 s | 26.98 | 2.95 MB |
| H100 `--scale 1.0` | ~37 s | 27.24 | 2.94 MB |

## Not done yet

Storage mode (read/write Supabase + `mint-work` by `scan_id`), keyframes / `bbox` / `sha256` / `stage`
events for the passport contract, metric scale, and testing on more objects.
