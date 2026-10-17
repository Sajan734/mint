# Scan handoff (scanner → gsplat)

What the Mint scanner hands to reconstruction (Role A): one folder per scan in Supabase Storage, **`scans/{scan_id}/`** (download: `python3 tools/fetch_scan.py latest`, see [supabase/README.md](supabase/README.md)). AirDrop zip as a fallback.

```
{scan_id}/
  video.mp4       960×720 H.264, 20 s at ~30 fps (real capture timestamps), no B-frames
  poses.jsonl     one JSON line per video frame, in order: line n = decoded frame n
  capture.json    session info: device, duration, frame count, sizes, exposure lock
  thumb.jpg       first frame, upright
```

**How scans are taken (current app):** the item sits on a sheet of paper; the phone stays still; the paper is turned through two laps (lap 2 with the phone raised). The app records only; it doesn't track the turn, so `pose` = `pose_world` = the raw ARKit camera pose. **Relative to the item the camera orbits, but in ARKit's world the camera barely moves and the item turns**, so: mask the item (SAM 2) and get item-relative poses from VGGT on the masked frames, as in the hand-held-video fallback. ARKit poses still give metric scale and the (static) camera height. Older scans in `tools/` notes had manifests/keyframes; current ones don't.

## Conventions (CLAUDE.md §6.2, D2/D3)

- **Orientation:** frames are in **sensor (landscape) orientation**, not rotated to portrait. The phone was held upright, so the item appears rotated 90° in players. Don't rotate the frames, or K stops matching.
- **Intrinsics:** `intrinsics` is K in pixels of *that* image: video lines use 960×720, manifest keyframes use 1440×1080. (ARKit's K for 1920×1440, scaled.)
- **Poses:** row-major 4×4, camera-to-world, **raw ARKit camera axes** (+x right, +y up, camera looks down −z). Convert once: `T_cv = translate(−anchor) · T · diag(1,−1,−1,1)`.
  - `pose_world`: raw ARKit `camera.transform`.
  - `pose`: camera-to-**item**. Today the item doesn't move, so `pose == pose_world`. Once hand-turn tracking lands, `pose` stays consistent with the item while it's turned, and is **absent** (`state: "handling"`) while a hand is moving it. Use `pose` and skip lines without it.
- **Anchor / item centre:** `manifest.anchor` = item centre (half-way up the item), metres, same frame as `pose`. +Y up = gravity.
- **ARKit drift:** over a lap ARKit's world slides by a few cm (measured: ~3.5–4 cm on a fast lap round a mouse). The app tracks the item from its masks, and every `poses.jsonl` line carries `item_centre`: where the item is *in that frame's* ARKit world. To cancel the drift's translation, re-centre each frame on its own `item_centre` instead of one fixed anchor. VGGT refinement still applies.
- **Metric:** ARKit metres.

## Turntable scans (`capture.json` → `"mode": "turntable"`)

The usual scan now: the item sits on a sheet of paper, the phone stays still, and the user turns the paper (two laps, two heights). The app measures the sheet's position and angle in every frame (top-down view of the table, straight-edge fit; on the first real recording: tracked in 565/566 frames, 0.5° median vs an independent detector).

- `pose` = camera in the **item's frame** = ARKit world at the moment Start was pressed, with the paper's turn and slide undone. Train on `pose`, not `pose_world`.
- Lines with `"state": "paper_lost"` have no `pose` (hand over the sheet, or it left the view). Skip them.
- **The background moves relative to the item** (the room is still, the item turns), so masking is mandatory (SAM 2). The sheet turns *with* the item, so it's consistent and can stay in or be masked out.
- `item_centre` per frame = where the item is in that frame's ARKit world (turns and slides with the paper).
- `paper_m` in `capture.json` = the sheet's measured size.

## Extract frames without breaking frame ↔ pose alignment

```bash
ffmpeg -i video.mp4 -vsync passthrough -start_number 0 frames/%05d.png   # never resample fps
```
Or with OpenCV: read frames in order; frame i ↔ `poses.jsonl` line i. Each line also has `t_ms` (from the first frame) if you'd rather match on time.

## Check a scan before training

```bash
cd scanner/tools && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python check_scan.py ~/Downloads/mint-1a2b3c4d.zip --overlays /tmp/overlays
```
Checks the schema, frame counts, hashes, and that the item centre projects onto the item in every frame (look at the overlays: the crosshair should sit on the item).

Also in `tools/`: `paper_check.swift` (runs the app's paper tracker + coverage on a turntable recording, on the Mac), `turntable_check.swift` (Vision's rectangle detector, for comparison), `refind_eval.py` (can the item be re-found after a turn? measured against ARKit) and `hull_check.swift` (re-runs the app's multi-view item tracking on a recording, with Vision on the Mac; build steps at the top of the file).

## `poses.jsonl` line

```json
{"counted":true,"frame":12,"intrinsics":[[...3×3...]],"pose":[[...4×4...]],"pose_world":[[...4×4...]],
 "item_centre":[0.17,-0.15,0.14],"segment":"az090_el28","sharpness":143.2,"state":"scanning","t_ms":400,"tracking":"normal"}
```
`counted` = this frame filled or improved a dome segment (a good keyframe candidate). `tracking` ≠ `normal` means ARKit was unsure, so treat that pose with suspicion.
