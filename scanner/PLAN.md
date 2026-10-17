# Scanner game plan (Role C, capture only)

Scope of this folder: the **iOS capture app** (M1, the M2 pop-up later) plus a **tiny upload signer**, so a scan lands somewhere the gsplat teammate (A) can download it. The stage view, demo player and seller key are Role C work too, but they come later (CLAUDE.md §11) and aren't covered here.

Everything lives under `scanner/` until merge. At merge time `scanner/ios/` → `ios/` (CLAUDE.md §12).

---

## 1. Key decisions (proposed)

### 1.1 Native iOS app, not a web app
iOS Safari has no WebXR `immersive-ar`, so a web page can't get ARKit camera poses or anchor a dome to a real object. A native Swift + ARKit app is the only way to get **metric, per-frame camera poses**, which is what makes splat training fast and lets us *prove* coverage (D1 in CLAUDE.md §8).

### 1.2 What the scan produces: MP4 + pose sidecar + keyframes
A wants an MP4. The architecture wants pose-tagged JPEGs. **We ship both from one capture:**

```
scans/{scan_id}/
  video.mp4          landscape (sensor orientation), 960×720 H.264, 30 fps, locked exposure/focus/WB
  poses.jsonl        one line per video frame: {frame, t_ms, pose (raw ARKit 4×4), intrinsics (3×3, video px), tracking, sharpness, segment}
  f000.jpg … fNNN.jpg  best sharp frame per dome segment (~24–60), 1440×1080, K scaled
  manifest.json      contracts/capture_manifest.schema.json (v3), coverage_pct, anchor
```

**720p = 960×720, not 1280×720 (decided with A).** The ARKit sensor image is 4:3 (1920×1440). Halving it to 960×720 keeps the whole field of view and K stays exact (`fx, fy, cx, cy` × 0.5). Cropping to 16:9 would throw away the top and bottom of every frame and shift `cy`. At ~4 Mbps a 25 s scan is ~12 MB.

- **MP4 only** → A falls back to VGGT-only poses (no metric scale, slower). That still works.
- **MP4 + `poses.jsonl`** → A gets ARKit poses for every video frame for free (frame N ↔ line N).
- **JPEGs + manifest** → the locked v3 contract, so the merge needs no changes.

### 1.3 How the scan reaches A: Supabase Storage (cloud bucket)
```
iPhone ──POST /scans──▶ signer (tiny API, holds the service key) ──▶ signed upload URLs
iPhone ──PUT files────▶ Supabase Storage bucket `scans/{scan_id}/…`
A (Modal GPU) ──download with service key──▶ trains gsplat
```
- No secrets in the app (invariant §6.6 #7): the app only ever sees **signed upload URLs**.
- The signer is ~40 lines (FastAPI on Modal, or a Supabase Edge Function) in `scanner/server/`. At merge it becomes D's `POST /scans` (same shape as ARCHITECTURE.md §10).
- Upload starts **during** the scan (keyframes stream as they're captured, 4 in flight); the MP4 goes up when recording stops. About 25 MB for 25 s at 8 Mbps.
- **Fallback (works tonight, needs no cloud):** a "Share" button → AirDrop the `.mp4` + `poses.jsonl` zip straight to A's Mac.

### 1.4 Full coverage: the dome and the visual cues
24 segments = **2 elevation bands (~20° and ~50°) × 12 azimuths (30° each)** around the tap anchor. Each frame: anchor→camera direction → (azimuth, elevation) → segment. A segment fills when a frame from that direction is **sharp** (Laplacian variance on a 160 px thumbnail) **and** steady (low angular velocity from ARKit) **and** tracking is `.normal`.

Cues, in order of importance:
1. **AR dome** (RealityKit) anchored around the object. Empty segments are faint grey, filled ones turn **mint `#3DDC97`** with a pop.
2. **Coverage ring HUD** (2D, bottom of screen): two concentric rings of 12 ticks, a big `%`, and a "you are here" marker.
3. **Guidance arrow + text** pointing to the nearest empty segment: "Keep walking left →", "Raise the phone — top ring next", "Lower the phone".
4. **Quality warnings** in plain language: "Too fast. Slow down a little." · "Too dark." · "Lost tracking. Point at the table." · "Get a bit closer."
5. **Haptic tick** on every segment fill; success haptic + seal animation at 90%.
6. **Auto-finish at ≥ 90% coverage** (22 of 24 segments), then upload. "Coverage verified. Nothing hidden."

---

## 2. Chunks (each one ends with something you can test on the phone)

H = hours since Fri Oct 16, 10 PM ET. Gates are from CLAUDE.md §10.

| # | Chunk | Done when | Target |
|---|---|---|---|
| **0** | **Toolchain**: install Xcode, sign in with your Apple ID, enable Developer Mode on the iPhone; `brew install xcodegen` | A blank app runs on your iPhone | **NOW** (★ H1 is overdue without this) |
| **1** | **Skeleton + AR session**: XcodeGen project in `scanner/ios/`, SwiftUI shell, `ARWorldTrackingConfiguration` + horizontal planes, tap → raycast → anchor + marker; lock exposure/focus/WB via `configurableCaptureDeviceForPrimaryCamera` | Tap the table next to an object and a marker sticks to it while you walk around | H1–H2 |
| **2** | **Dome + coverage engine**: segment maths (pure Swift, unit-tested), RealityKit dome, sharpness + motion gate, segment fill + haptics | Walk around and the segments fill; % climbs to 90 | H2–H3 |
| **3** | **Recording**: `AVAssetWriter` MP4 from `ARFrame.capturedImage` (landscape), `poses.jsonl` per frame, best JPEG per segment + scaled K, `manifest.json`; saved to the app's Documents; **Share/AirDrop export** | You AirDrop a scan to A and A can open the MP4 and read the poses | H3 |
| **4** | **Cloud transfer**: Supabase project + `scans` bucket, `scanner/server/` signer, background uploader (keyframes during the scan, MP4 at the end, retries), status UI | A downloads `scans/{id}/` from the bucket with a script in `scanner/tools/` | **★ H4** |
| **5** | **Guidance polish**: coverage ring HUD, direction arrow, height hints, warnings, auto-finish, seal moment, brand palette | A non-team person scans to 90% in 20–25 s, unassisted, 3 of 3 objects | H4–H4.5 |
| **6** | **Handover mode + recognition pop-up**: 10 s rescan (`kind: handover`); first-frame upload + pop-up (once A's recognition endpoint exists) | Model name pops up mid-scan | after H8 |

Checks we'll add along the way: unit tests for segment maths, K scaling and pose serialization (test-first, CLAUDE.md §1.10), plus a `scanner/tools/check_scan.py` that validates a downloaded scan against the manifest schema and overlays the projected anchor on a few frames (proves the poses and K are right before A trains on them).

---

## 3. Answers so far (Fri Oct 16, ~H1.5)

| Question | Answer |
|---|---|
| Hardware | **iPhone 14, iOS 26.6.2** (dev phone, no LiDAR). Teammate: **iPhone 17 Pro Max, iOS 26.6.2** (has LiDAR, so it can fall back to Object Capture). Only one Mac on the team, this one. Xcode isn't installed yet. |
| A's format | MP4, 720p is fine → 960×720 (see §1.2). |
| Supabase | Nobody has made it yet → **we create the team project** (it becomes D's at merge). |
| Signer host | **Supabase Edge Function.** A's GPU side is on Modal anyway and only needs to read the bucket. |
| Vultr | **Not on the critical path tonight.** See §4. |

## 4. Vultr (prize category)

Recommendation: **don't move capture or transfer onto Vultr now.** Supabase Storage + signed URLs is a few clicks and already in the architecture; Vultr adds another account, a VM to secure and keep alive, and a second place for scans to live, right when the H4 gate is due.

If the team wants the prize, the cheapest credible integration is **after the H4 gate**: Vultr **Object Storage** is S3-compatible, so the uploader can mirror `scans/{scan_id}/` to a Vultr bucket with the same signed-URL flow (one more signer route), or A runs gsplat on a **Vultr Cloud GPU** instead of Modal. Either way, check the prize rules first: many sponsor prizes require the product to *run* on their cloud, not just touch it. That's a team decision (CLAUDE.md §1.11). Raise it in the channel.

## 5. Progress

| Chunk | Status |
|---|---|
| 0 Toolchain | ⏳ Xcode needs installing. `xcodegen` installed via Homebrew. |
| 1 Skeleton + AR | ✅ code written: `ios/project.yml`, `MintApp`, `ScanSession` (world tracking, horizontal planes, 1920×1440 format, tap → raycast → anchor dropped onto the table), `CameraLock`, coaching overlay. **Not yet compiled for iOS** (needs Xcode). |
| 2 Dome + coverage | ✅ code written: `CoverageKit` (24 segments, sharpness gate, motion/distance/light gates, guidance), `DomeEntity` (RealityKit tiles, near-side fade, pop), `CoverageRingView`, haptics, issue debounce, auto-finish at 22/24. **CoverageKit tests pass** on the Mac via a stand-in harness; run ⌘U once Xcode is in. |
| 3 Recording | next |
