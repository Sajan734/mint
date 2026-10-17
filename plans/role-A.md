# Role A — Reconstruction (v3)

**Mission:** turn a 20-second AR scan into a photoreal, metric, sealed passport in **≤ 100 s**, and supply the curated reference images the comparison engine depends on.
**Owns:** M2 (recognition), M3, M4, M5 (references), M17 (golden scans, with C), N4 (with C). Modal GPU image + warm containers. Code: `backend/recon/`, `data/refs/`.
**Sleeps:** H6.5–H10 (Sat 4:30–8 AM, after the H6 gate). Nap H25–H26.5.
**Read first:** [CLAUDE.md](../CLAUDE.md) §6, [ARCHITECTURE.md §2 conventions](../ARCHITECTURE.md#2-conventions-locked-at-h1), [§3 Pipeline 1](../ARCHITECTURE.md#3-pipeline-1--scan-to-passport), [§4.1 references](../ARCHITECTURE.md#41-references-a).

## Interfaces

| Direction | Contract | With | By |
|---|---|---|---|
| consumes | [capture_manifest](../contracts/capture_manifest.schema.json) (raw ARKit poses, K, segments) + frames | C | H4 |
| produces | [recognition](../contracts/recognition.schema.json) → realtime `recognition` | C, D, stage | H3 |
| produces | [reference_set](../contracts/reference_set.schema.json) + images + masks in `data/refs/` | B | H1–H3 |
| produces | [passport](../contracts/passport.schema.json): `.spz` (public), `.ply` on `mint-work`, keyframes (OpenCV poses) | B, D | hand-held splat H4, AR splat H6 |
| produces | `GET /keyframe` (tap-for-photo) | D | H13 |
| produces | `stage` events for every step; `scan_sha256` | all | H6 / H16 |
| shares | GPU base image pins (torch, CUDA, gsplat) with B | B | H1 |

## Fixtures

Real only: 3 demo-object AR scans (from C's app after H4; before that, a hand-held phone video → frames), 3–5 official references per object with source URLs, a ruler measurement per object (metric check), one bad scan (blurry, hand in frame).

## Pre-hack (no project code)

- [ ] Throwaway Modal image with pinned torch, gsplat, SAM 2, VGGT, DINOv2; time one splat on **L4 vs A100** → D12.
- [ ] VLM benchmark on photos of the demo objects (latency, reads brand/model/variant) → D13.
- [ ] Choose 3–5 **matte, textured, asymmetric** demo objects that have official product photos of the **exact variant**.
- [ ] Curate 3–5 references each: real photos over renders, varied angles, clean backgrounds; save with `source_url`.

## Tasks

| # | Window | Task | Done when |
|---|---|---|---|
| A1 | H0–1 | Modal app `mint-recon`; Volumes `mint-weights` (SAM 2, VGGT, DINOv2) and `mint-work`; `Reconstructor` with `@modal.enter`; stage-event stubs; commit `data/refs/` | Warm call < 20 s; **★ H1** |
| A2 | H1–3 | **De-risk** with a hand-held video: frames → SAM 2 → VGGT-only poses → gsplat → `.spz`. Recognition endpoint: one VLM call, strict JSON → `recognition`. Reference product masks (SAM 2 or studio-white threshold) | Splat of object 1 loads in Spark; recognition 3 of 3 in < 4 s |
| A3 | H3–4 | Hand the hand-held splat + keyframes to B. Manifest ingest: `T_cv = translate(−anchor) · T_arkit · diag(1,−1,−1,1)`; verify K matches the saved JPEG size | Unit test: projecting a known point with ARKit pose vs converted pose gives the same pixel |
| A4 | H4–6 | Real AR scans: SAM 2 from the recognition box + **hand filter** (drop frames where a hand overlaps > ~2% of the item mask) → ARKit init + VGGT refine (Sim(3) to ARKit, keep metric; fall back to ARKit if reprojection worsens) → gsplat with alpha loss → export | **★ H6:** real AR scan → splat in browser |
| A5 | H10–13 | Keyframe index `{pose, K, sharpness, segment, thumb_path}` + item-masked thumbs; `GET /keyframe` (project, occlusion check vs splat depth ±1 cm, score = sharpness × view angle × centrality); tune to **≤ 100 s** (iterations, resolution, Gaussian cap ≤ ~300k, frame count) | Timed ≤ 100 s on 3 of 3; 10 random taps per object open the right photo |
| A6 | H13–16 | `scan_sha256` (frame hashes + `.spz` hash, canonical JSON) → seal hook; quality warnings (coverage < 90%, too few sharp frames, high VGGT residual); eval scans with D; start scanning the **8-item batch** | Hash stored; warnings show in the app |
| A7 | H16–20 | Golden assets with C's recorder: `item-live`, `obj-2`, `obj-3`, `batch-8`, `handover-golden`, `wrong-ref` (all real runs); keep-alive ping | Each replays offline in C's player |
| A8 | H20–34 | Fixes only; timed runs logged into DEMO.md; `min_containers=1` from H28; rehearse; lead 3D questions in Q&A | Timings recorded |
| N4 | after gate 4 | Underside flip pass merged into the splat (with C) | — |

## Fallbacks

| If | Then |
|---|---|
| AR app late (H4 fails) | Keep producing splats from hand-held video + VGGT; by H6 agree the fallback with C (Object Capture on LiDAR, or hand-held) |
| VGGT refinement hurts or OOMs | Use ARKit poses directly |
| SAM 2 drifts | Re-seed from the box every ~15 frames; rembg |
| Over 100 s | Fewer frames and iterations, lower resolution; the demo already uses a cached splat |
| VLM slow or wrong | Manual label; seed masking from a centre box |
| `.spz` export fails | Ship `.ply` (check iPhone performance) |
