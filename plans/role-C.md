# Role C — Capture app and stage (v3)

**Mission:** a native iOS app that makes a 20-second, coverage-verified, pose-tagged scan feel effortless, and a stage view that makes the whole pipeline visible to judges, live or replayed.
**Owns:** M1, the M2 live UI, M16, M17 (with A), N4 (with A), the seller key on the iPhone. Code: `ios/`, `web/app/stage/`, `web/lib/demo/`, `web/public/demo/`.
**Sleeps:** H4.5–H8 (Sat 2:30–6 AM, after the H4 gate). Nap H26.5–H28.
**Read first:** [ARCHITECTURE.md §2 conventions](../ARCHITECTURE.md#2-conventions-locked-at-h1) (raw ARKit poses, landscape frames, scaled K), [§3 Pipeline 1](../ARCHITECTURE.md#3-pipeline-1--scan-to-passport), [§11 events](../ARCHITECTURE.md#11-realtime-events), [§13 stage + demo mode](../ARCHITECTURE.md#13-stage-view-and-demo-mode-c), [CLAUDE.md §15](../CLAUDE.md#15-brand-and-experience).

## Interfaces

| Direction | Contract | With | By |
|---|---|---|---|
| produces | [capture_manifest](../contracts/capture_manifest.schema.json): raw ARKit `camera.transform`, K scaled to the saved JPEG (landscape), `segment`, `anchor`, `coverage_pct` | A, B | H4 |
| produces | `capture_progress` events | stage | H4.5 |
| consumes | `recognition`, `passport_ready` | A | H4.5 |
| consumes | `registration_progress`, `registration`, `anomaly_map`, `candidates`, `region`, `verdict`, `identity` | B | H10–H13 |
| consumes | `price`, `statement`, `handover_result`, `record_ready`, `sealed` | D | H16 |
| produces | Seller signatures: CryptoKit Ed25519 over raw SHA-256 (`/scans/{id}/seal`, `/deals/{id}/sign`) | D | H16 (interop by H4) |
| produces | Demo recorder JSONL ([realtime_event](../contracts/realtime_event.schema.json) + `t_ms`) and player | everyone | H13 / H20 |

## Fixtures

Real scans of the demo objects from the app itself; real event streams recorded from real runs (never hand-written JSONL).

## Pre-hack (no project code)

- [ ] Mac + Xcode + iPhone; device signing works (free provisioning is fine).
- [ ] **Does anyone have a LiDAR iPhone?** (Object Capture fallback.)
- [ ] Brand draft: mark, palette tokens, type, seal + guilloche (CLAUDE.md §15).

## Tasks

| # | Window | Task | Done when |
|---|---|---|---|
| C1 | H0–1 | Xcode project runs on device; `ARWorldTrackingConfiguration` + horizontal plane detection; tap → raycast → `ARAnchor` | **★ H1** |
| C2 | H1–3 | AR dome (RealityKit): 2 elevations × 12 azimuths around the anchor; per frame pick the segment from the anchor→camera direction; save when the segment is empty **and** the frame is sharp (Laplacian variance on a thumbnail) **and** angular velocity is low. Save JPEG in **sensor orientation** (e.g. 1440×1080), raw pose, K scaled to that size, segment id. **Lock exposure, focus, WB at scan start** | Dome fills while walking around; frames + poses on disk |
| C3 | H3–4 | Upload: `POST /scans` → signed URLs; first sharp frame + `/first-frame` immediately; stream the rest (4 in flight); manifest + `/complete` automatically at **≥ 90% coverage** | **★ H4:** dome anchored and filling; frames + poses upload |
| C4 | H4–4.5 | Recognition pop-up in the app; `capture_progress` events | Model pops up mid-scan |
| — | H4.5–8 | 💤 | — |
| C5 | H8–10 | Stage view `/stage/[batchId]`: dome mirror, splat reveal (points densify), **registration snap** (reference image floats over the model, snaps, IoU ticks), per-stage timing bar | Snap plays from B's events |
| C6 | H10–13 | Stage: anomaly heatmap, **noise fade** from `candidates`, region glow, ledger build; demo **recorder** (JSONL + assets → `demo/{key}/`); app **handover mode** (10 s, `kind: handover`, `deal_id`) | A live run recorded |
| C7 | H13–16 | **Seller key**: CryptoKit `Curve25519.Signing` in the Keychain; auto-seal on `passport_ready`; seller signing at handover. Stage: statement stack, red beside amber, stamp + verify sweep | App signature verifies in PyNaCl and tweetnacl |
| C8 | H16–20 | Demo **player** (`?demo=`), always-visible **Replay** pill, offline build (`pnpm build && pnpm start`); full demo on a new object; **backup video on two phones** | **★ H20** (feature freeze) |
| C9 | H20–33 | Polish: projector readability, reduced motion, timing; release tag `v1.0-demo` by H33; rehearse the scan and rescan beats | Tagged |
| N4 | after gate 4 | Underside flip pass capture flow (with A) | — |

## Fallbacks

| If | Then |
|---|---|
| AR dome not working by H4 | Keep building; by H6 decide with A: Apple Object Capture on a LiDAR iPhone, or hand-held video + VGGT (coverage shown after upload) |
| CryptoKit signatures don't verify | Sign in a web view with tweetnacl |
| App crashes on stage | Relaunch once; then the recorded `item-live` capture |
| Wi-Fi down | Hotspot → offline demo build |
| Laptop dies | Backup laptop, then the backup video |
