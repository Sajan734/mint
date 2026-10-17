# Role B — Comparison engine (v3)

**Mission:** solve where each manufacturer photo's camera was relative to the splat, find wear, damage and missing parts that persist across references, check identity, catch new damage at handover, and give every region a typed, calibrated verdict, inside **15 s per item** and **20 s per handover**.
**Owns:** M6, M7, M8, M9, M14 (engine), M18 (with D), N5. Code: `backend/compare/`, `backend/decide/`, `eval/` metrics.
**Sleeps:** H3–H6.5 (Sat 1–4:30 AM, while waiting for the first real splat). Nap H23.5–H25.
**Read first:** [ARCHITECTURE.md §4 Pipeline 2](../ARCHITECTURE.md#4-pipeline-2--condition-vs-references-the-core), [§5 Pipeline 3](../ARCHITECTURE.md#5-pipeline-3--handover-check), [§6 Decisions](../ARCHITECTURE.md#6-decision-layer-b).

## Interfaces

| Direction | Contract | With | By |
|---|---|---|---|
| consumes | [passport](../contracts/passport.schema.json) (`.ply`, keyframes, OpenCV poses) | A | H4 (hand-held), H6 (AR) |
| consumes | [reference_set](../contracts/reference_set.schema.json) + masks | A | H1–H3 |
| consumes | handover [capture_manifest](../contracts/capture_manifest.schema.json) | C | H10 |
| produces | [registration](../contracts/registration.schema.json) + [registration_progress](../contracts/registration_progress.schema.json) events | D, C (stage) | H10 |
| produces | [region](../contracts/region.schema.json), [verdict](../contracts/verdict.schema.json), [identity](../contracts/identity.schema.json), `anomaly_map`, `candidates` | D, C | H13 |
| owns routes | `POST /items/{id}/condition`, `POST /deals/{id}/handover` | D (skeleton) | H13 |
| produces | Eval numbers table | D | H26 |

## Fixtures

Real only: real phone photos of each demo object + its curated references (for H1–H3, before any splat); A's hand-held splat (H4) and AR splats (H6); eval set from D (listing scan, 3 handover scans with logged changes, 2 no-change rescans per object; existing wear logged by hand); a **deliberately wrong reference set** for the identity test.

## Pre-hack

- [ ] Confirm **Jev** access, call shapes (Choice/Score/Noul), latency for a batch of ~20 regions.
- [ ] Read gsplat's differentiable rasterization (camera gradients) and LightGlue/ALIKED usage.

## Tasks

| # | Window | Task | Done when |
|---|---|---|---|
| B1 | H0–1 | `Comparator` Modal class (DINOv2, ALIKED/SuperPoint + LightGlue, gsplat, SAM 2) on A's pinned image; `DecisionEngine` interface + `apply_rules` skeleton + constants from `contracts/constants/price_v3.json` (thresholds) | Warm load OK; **★ H1** |
| B2 | H1–3 | **Lighting risk first.** Photo-only baseline: homography-align real phone photos to references and diff. Build primitives on the same data: histogram matching inside the mask, DINOv2 patch distance, high-passed Lab difference, edge erosion | Clear answer posted to the team: does lighting dominate, and do the primitives suppress it? |
| — | H3–6.5 | 💤 | — |
| B3 | H6.5–8 | Render the splat at keyframe poses (self-check: render ≈ photo, overlay aligned). Pre-render the **coarse viewpoint sphere** (e.g. 8 elevations × 24 azimuths × 3 focals, low-res) and cache on `mint-work` | Overlays align to a couple of pixels |
| B4 | H8–10 | Coarse pose (DINOv2 global + normalised silhouette IoU, top-k) → fine pose (LightGlue in both masks, lift with splat depth, **PnP-RANSAC with focal sweep**) → **render-and-optimize** (pose + focal, soft-silhouette IoU + keypoint reprojection, ½-res, early stop); emit `registration_progress` every ~10 iterations; accept IoU ≥ 0.85 | **★ H10:** IoU ≥ 0.85 on one object |
| B5 | H10–13 | Anomaly maps (histogram match, DINOv2 + high-passed Lab + silhouette delta); **persistence ≥ 2 references** via 3D lifting + visibility; HDBSCAN regions + features + evidence (render, reference, nearest keyframe); `candidates` event. Handover: localize frames into the seller splat (nearest keyframes, LightGlue in mask, PnP vs splat depth), render, diff, vote, cluster, wipe pairs | **★ H13:** anomaly regions on 3 objects; handover diff on one pair |
| B6 | H13–16 | Identity score (IoU + inlier ratio) and wrong-reference test; `apply_rules`: 0.85 / 0.5 routing, **hard floor (≥ 70% agreement)**, price-neutral classes, confident artifacts dropped, `present_before` from disclosed-region overlap; RulesV0 → calibrated LogReg + GBR (Platt/temperature); Jev with a 3 s timeout | Verdicts < 5 s per item; unit test proves no model drops a floor-protected region |
| B7 | H16–20 | Latency: refs in parallel, cached spheres, ½-res refine, capped handover views → **≤ 15 s** registration + comparison, **≤ 20 s** handover; label eval regions with D | Timed on 1 object |
| B8 | H20–26 | Eval: registration mean IoU + pose success rate; anomaly precision/recall vs references; handover precision/recall; false regions per clean scan; photo-only baseline; Jev vs LogReg (accuracy, ECE); latencies; dataset size | **★ H26:** numbers table to D |
| B9 | H26–29 | Live runs 3 of 3; N5 reliability diagram; rehearse beats 0:55–1:45 and 2:45–3:35 | **★ H29** |

## Fallbacks

| If | Then |
|---|---|
| Fine pose fails | Coarse pose only, best reference kept |
| A reference won't register | Skip it; need ≥ 3 accepted, otherwise try another reference or object |
| DINOv2 too slow | Lab difference only (`feature_dist = 0`, noted) |
| HDBSCAN unstable | DBSCAN with eps in metres |
| Handover localization fails | Slower rescan; golden result |
| Jev down or slow | Fallback classifier (or RulesV0 before H16) |
