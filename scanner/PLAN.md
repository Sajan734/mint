# Scanner game plan (Role C, capture only)

> **Current direction (Sat Oct 17):** we run the demos ourselves and the turntable method reliably gives a good scan, so the app's job is now just (1) **look great** for the ~25 s the judges watch and (2) **get the MP4 into Supabase**. All guidance/gating (distance, sharpness, coverage checkpoints, locking) was removed: live item outline (the item = what the sheet of paper encloses, `ItemOnPaper`; outlined the mouse in 114/114 sampled frames of the turntable recording where Vision's subject segmentation picked the paper, the hand or a knee) + holographic scan overlay, 3·2·1, a pass that runs until the ring is tapped (45 s cap: Storage takes 50 MB per file), then **Scan again** (another pass: flipped over, other angles) or **Done** (sends every pass of the item under one `scan_id`; see HANDOFF.md) or discard the last pass.

> **Coverage % is measured, not scripted (Sat Oct 17, ~10:30):** the only measurement is how far the **paper has turned relative to the camera**. `SheetAngle` projects the sheet's outline (the `ItemOnPaper` mask, already computed for the item outline) onto a horizontal plane using only the camera's tilt, so it needs no table plane, item position or lock, and ARKit's world slowly turning cancels out. Straight edges → angle mod 90°, `PaperTurn` unwraps it. `TurnCoverage`: 36 slices of the item's sides (one ring = one lap at any height; a 2-height mode exists but isn't shown); a slice fills only while within 25° of facing the camera (cos-weighted, ~0.5 s), so 100% means the paper really went round (on `mint-33218a6e`: 54% at half a turn, 100% at 315°). The ring is a guide: 100% doesn't end the pass, and you can finish below it. The overlay paints each part of the silhouette by how well that side has been seen (upright-cylinder model), so it turns mintier as the paper turns; the rings show the real slices. **Measured** on `mint-33218a6e` (white ruled paper, beige table, hands on the corners) at the phone's ~7.5 reads/s: 142/142 reads used, total turn 380° vs 378° from the top-down tracker, median 1.5° / 95th pct 4.9° apart; 3 ms/read on the Mac. Check a recording: `tools/turn_check.swift` (`--render` paints the tint onto the frames). **Needs a device test.** The measurement work below (hull tracking, paper tracker) is kept in CoverageKit and documented, but the app doesn't use it.

Scope: the **iOS capture app** plus the handoff to reconstruction (A). Stage view, demo player and seller key are Role C work too, but they come later (CLAUDE.md §11). Everything lives under `scanner/` until merge; at merge `scanner/ios/` → `ios/` (CLAUDE.md §12). What A receives is specified in [HANDOFF.md](HANDOFF.md).

**Demo target:** a judge picks any item. Point the phone at it, it's found and sized automatically, tap Start, and in **≤ 20 s** you have full coverage by walking, turning the item by hand, or both. One scan, and it has to look good.

---

## 1. Decisions

| Topic | Decision | Why |
|---|---|---|
| Platform | Native Swift + ARKit | Safari has no WebXR AR on iOS; only ARKit gives metric camera poses |
| Video | **960×720** H.264 MP4, sensor orientation, no B-frames, 8 Mbps | "720p" without cropping the 4:3 sensor, so K stays exact (×0.5); frame n ↔ pose line n |
| Extra files | `poses.jsonl` (pose per video frame), best JPEG per segment, `manifest.json` (contract v3), `capture.json` | A gets metric poses for free; contract stays intact for the merge |
| Transfer | AirDrop/Files now (`mint-{id}.zip`), then a Supabase Storage bucket via an Edge Function signer | No cloud needed tonight; no secrets in the app |
| Find + size the item | Vision subject mask → ARKit surface hits inside it → table = highest plane clearly *below* the hits → footprint + height. Lock once 3 reads agree, then **hold** | No tap, no pinch. No cm on screen (transparent/plain items can't be measured well, and a wrong number costs trust) |
| Coverage rule | **One ring**: 12 sectors at any height 10–75°, done at 11/12 | Two rings forced two laps: real scan = 13 s for the top ring + 23 s crouching for the bottom |
| AR visual | 12 arcs **on the table** around the item's base; your current arc lights up | The dome tiles washed over the item |
| Performance | Sharpness/thumbnail via Accelerate; ⌘R runs Release | Plain-Swift pixel loops took ~47 ms/frame in Debug → video at 13.8 fps |
| Turn the item by hand | **Still periods are exact; turns are re-measured** (§2) | Precise, with no drift and no props |
| Vultr | Not now (see the old note in git history: only after the core works; check prize rules) | Focus |

## 2. Turning the item by hand (the precise way)

The user can: scan a side → pick the item up or turn it → put it down → scan more → repeat.

1. **While the item is still**, ARKit's camera poses are exact relative to it (it's just a static scene). Coverage counts normally.
2. **Building a map:** during still periods the app detects SIFT features on the item (inside its mask) in keyframes and triangulates them with the known poses. That gives 3D points + descriptors in the **item's frame**, in metres.
3. **Hands:** Vision hand-pose detection. When a hand is on the item, the state becomes `handling`: coverage pauses, the dome turns grey ("Let go when it's turned"), and frames are still recorded but tagged.
4. **Re-finding it:** when the hands leave and the item is still again, match the current frame's features against the map → **PnP-RANSAC** → the camera's pose relative to the item, so the item's new pose in the world = camera pose ∘ (camera-relative-to-item)⁻¹. It's refined over several frames. This handles any rotation, including flips. Error doesn't accumulate because every re-find is against the map, not the previous frame.
5. **The dome snaps** to the item's new orientation. The filled side has turned away, the grey side faces you, and you keep scanning. Coverage is counted in the **item's frame**, so it's honest.
6. **Upright prior:** if the turn kept the item upright (tilt < ~8°), the pose is constrained to a turn about the vertical axis + a slide on the table. That makes it more stable.
7. **Guidance:** after half the reachable sides are full: "Give it a quarter turn ⟳". If re-finding fails: "Turn it back a little" (less change from what was seen). Too plain to track → "Walk around it instead".
8. **What A gets:** `pose` = camera-to-item for every still frame (exact within each still period, re-found between them), absent while handling. The background moves relative to the item between periods, so A must mask, which they already do with SAM 2. VGGT refine still applies.

**Measure first:** before writing this on the phone, it's prototyped in Python + OpenCV on **real recordings from the app** (scan, turn, scan), with numbers: re-find success rate, reprojection error, and pose agreement with frames where the item is known not to have moved. Then ported to the phone with OpenCV ([yeatse/opencv-spm](https://github.com/yeatse/opencv-spm) 4.13 via SPM) behind an Obj-C++ wrapper.

## 2b. Keeping the ring on the item (measured on real scans)

- **Finding it:** ARKit's own 3D feature points inside the Vision mask; the table = highest plane at the bottom of those points. Flat instances (laptop, mousepad) are skipped; once locked, detection sticks to the instance under the tracked item.
- **ARKit drifts** a few cm over a lap (`mint-40c3610d`: ~3.5–4 cm). A ring placed once at Start slides off the item even if it was perfect at Start.
- **Tracking:** a visual hull from the most recent views spanning ≥ 60° (masks + exact poses), plus a per-view nudge that centres the item's projected extent on the mask. Wrong masks are refused once tracking.
- **Result on the cluttered-table recording** (vs an offline ±45-frame reference): ring position error, median **1.6 cm → 0.8 cm**; late in the lap **3.6–4.9 cm → ~1 cm**.

## 2c. Turntable (the main method from now on)

The item sits on a sheet of paper; the phone stays still; the user turns the paper: lap 1 low (outer ring), lap 2 with the phone raised (inner ring), ~20 s. The app follows the **paper**, not the item, so it works whatever the item looks like.

- Each frame the camera image is resampled onto a top-down 50 × 50 cm map of the table (2.5 mm cells). Paper vs table by colour strength (paper ~2, beige table ~43); the sheet's angle from its straight edges (histogram, then a line fit per side, iterated: ≤ 0.3° on synthetic sheets at any angle); continuous across turns; centre from the edges + the known size when a hand covers a side.
- On the real recording (`mint-33218a6e`, one slow lap): tracked **565/566** frames, **0.5°** median vs Vision's rectangle detector, 1.5 ms/frame (Mac). Replaying the app's chain fills the low ring 12/12 in turning order.
- Coverage, the AR rings and the recorded `pose` are all in the item's frame. No paper under the item → the old walk-around mode.
- Feature re-finding (SIFT on the item) was measured first and rejected: fails beyond ~15° of turn.

## 3. Chunks

| # | Chunk | Done when | Status |
|---|---|---|---|
| 0 | Toolchain: Xcode, signing, Developer Mode | App runs on the iPhone 14 | ✅ |
| 1 | AR session, exposure/focus/WB lock, coaching overlay | Tracking works on device | ✅ |
| 2 | Dome + coverage engine + guidance + haptics | Walk around and it fills to 90% | ✅ tested on device |
| 3 | Auto-find + auto-size; recording; AirDrop export; `check_scan.py` | Point → bracket → Start → MP4 + poses + keyframes → AirDrop; `check_scan.py` OK with crosshairs on the item | ✅ first device scan `mint-30f063d2`: poses/K/orientation verified (crosshair on the item in every frame) |
| 3b | Fixes from that scan: 30 fps, one ring, hold-lock, ring on the table | Video ≥ 28 fps; one lap ≤ 20 s; lock doesn't flicker | ✅ `mint-0a705c19`: 30.1 fps, lap in 10.3 s |
| 3c | Find the item in clutter; keep the ring on it | Locks on a cluttered table; ring stays on the item through the lap | ✅ device: "locking was a lot better" |
| 4 | **Turntable mode** (paper tracking, two-lap coverage, rings turn with the paper, item-frame poses) | Two laps at two heights in ≤ 20 s; ring follows the paper | ✅ code + offline proof on `mint-33218a6e`; **needs a device test** |
| 4 | Prototype re-finding offline on real "scan → turn → scan" recordings | ≥ 95% of turns re-found; reprojection < 2 px; numbers written down | next |
| 5 | On-device: OpenCV, map building, hand detection, re-finding, dome follows the item | Turn the item mid-scan and the dome snaps to it; coverage stays right | |
| 6 | Guidance for turning + demo polish (snap animation, found bracket, seal moment, 20 s timer) | A first-time user finishes in ≤ 20 s | |
| 7 | Cloud transfer: Supabase bucket + Edge Function signer + background upload | A downloads `scans/{id}/` from the bucket | |
| 8 | Handover mode (10 s rescan, `kind: handover`) + recognition pop-up | — | later |
