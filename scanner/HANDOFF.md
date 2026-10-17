# Scan handoff (scanner → gsplat)

What the Mint scanner hands to reconstruction (Role A). One folder per scan, sent as `mint-{id}.zip` (AirDrop now; Supabase bucket `scans/{scan_id}/` later).

```
{scan_id}/
  video.mp4       960×720 H.264, ~30 fps (variable: real capture timestamps), no B-frames
  poses.jsonl     one JSON line per video frame, in order: line n = decoded frame n
  f{nnnnn}.jpg    best sharp frame per dome segment, 1440×1080; nnnnn = the video frame it came from
  manifest.json   contracts/capture_manifest.schema.json (v3): the keyframes
  capture.json    session info: item centre/size in metres, table height, duration, coverage
```

## Conventions (CLAUDE.md §6.2, D2/D3)

- **Orientation:** frames are in **sensor (landscape) orientation**, not rotated to portrait. The phone was held upright, so the item appears rotated 90° in players. Don't rotate the frames, or K stops matching.
- **Intrinsics:** `intrinsics` is K in pixels of *that* image: video lines use 960×720, manifest keyframes use 1440×1080. (ARKit's K for 1920×1440, scaled.)
- **Poses:** row-major 4×4, camera-to-world, **raw ARKit camera axes** (+x right, +y up, camera looks down −z). Convert once: `T_cv = translate(−anchor) · T · diag(1,−1,−1,1)`.
  - `pose_world`: raw ARKit `camera.transform`.
  - `pose`: camera-to-**item**. Today the item doesn't move, so `pose == pose_world`. Once hand-turn tracking lands, `pose` stays consistent with the item while it's turned, and is **absent** (`state: "handling"`) while a hand is moving it. Use `pose` and skip lines without it.
- **Anchor / item centre:** `manifest.anchor` = item centre (half-way up the item), metres, same frame as `pose`. +Y up = gravity.
- **Metric:** ARKit metres.

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

## `poses.jsonl` line

```json
{"counted":true,"frame":12,"intrinsics":[[...3×3...]],"pose":[[...4×4...]],"pose_world":[[...4×4...]],
 "segment":"az090_el20","sharpness":143.2,"state":"scanning","t_ms":400,"tracking":"normal"}
```
`counted` = this frame filled or improved a dome segment (a good keyframe candidate). `tracking` ≠ `normal` means ARKit was unsure, so treat that pose with suspicion.
