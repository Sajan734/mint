# Scanner game plan (Role C, capture only)

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
| Find + size the item | Vision subject mask (upright) → camera rays → table plane → width, height, centre | No tap, no pinch; works for any size that fits in view |
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

## 3. Chunks

| # | Chunk | Done when | Status |
|---|---|---|---|
| 0 | Toolchain: Xcode, signing, Developer Mode | App runs on the iPhone 14 | ✅ |
| 1 | AR session, exposure/focus/WB lock, coaching overlay | Tracking works on device | ✅ |
| 2 | Dome + coverage engine + guidance + haptics | Walk around and it fills to 90% | ✅ tested on device |
| 3 | **Auto-find + auto-size; recording; AirDrop export; `check_scan.py`** | Point → bracket → Start → MP4 + poses + keyframes → AirDrop; `check_scan.py` OK with crosshairs on the item | ✅ code, builds; **needs a device test** |
| 4 | Prototype re-finding offline on real "scan → turn → scan" recordings | ≥ 95% of turns re-found; reprojection < 2 px; numbers written down | next |
| 5 | On-device: OpenCV, map building, hand detection, re-finding, dome follows the item | Turn the item mid-scan and the dome snaps to it; coverage stays right | |
| 6 | Guidance for turning + demo polish (snap animation, found bracket, seal moment, 20 s timer) | A first-time user finishes in ≤ 20 s | |
| 7 | Cloud transfer: Supabase bucket + Edge Function signer + background upload | A downloads `scans/{id}/` from the bucket | |
| 8 | Handover mode (10 s rescan, `kind: handover`) + recognition pop-up | — | later |
