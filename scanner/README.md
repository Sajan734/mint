# Mint scanner (Role C capture)

The iOS app that captures a full-coverage scan of an item. The plan, decisions and chunks are in [PLAN.md](PLAN.md); what reconstruction receives is in [HANDOFF.md](HANDOFF.md); the role spec is in [role-C.md](role-C.md).

```
scanner/
  ios/
    project.yml                  XcodeGen config → Mint.xcodeproj (generated, not committed)
    Mint/                        the app: camera, live outline + scan overlay, recorder, uploader
    Packages/CoverageKit/        pure, unit-tested pieces (pose maths, file formats, fast sharpness, and the
                                 measured-but-shelved tracking work: hull, paper tracker)
  supabase/                      Edge Function (signed uploads) + bucket SQL + setup guide
```

## Run it on your iPhone

1. Install **Xcode** from the App Store, open it once, and let it install the iOS platform.
2. `sudo xcode-select -s /Applications/Xcode.app` (so command-line tools use Xcode, not CLT).
3. `cd scanner/ios && xcodegen` (re-run after adding or removing files).
4. `open Mint.xcodeproj` → target **Mint** → *Signing & Capabilities* → tick *Automatically manage signing*, choose your Apple ID team. If the bundle ID is taken, change `ca.htv11.mint.scanner` in `project.yml` and re-run xcodegen.
5. Plug in the iPhone; on the phone: *Settings → Privacy & Security → Developer Mode → On* (it restarts).
6. Pick the iPhone as the run destination, press **⌘R**. First launch: *Settings → General → VPN & Device Management → trust your developer certificate*.

Tests: **⌘U** in Xcode (runs `CoverageKitTests`), or `cd ios/Packages/CoverageKit && swift test`.

## Using it (the demo)

Put the item on a sheet of paper and point the phone at it: a glowing outline locks onto the item. Tap **Scan** → 3·2·1 → 20 s of recording: **lap 1** turn the paper slowly; at 10 s (haptic bump) **lap 2**, raise the phone and keep turning. It stops by itself, seals the capture, and uploads to Supabase with a live progress bar (setup: [supabase/README.md](supabase/README.md)). **Share** on the card AirDrops a zip as a fallback.

## Getting a scan off the phone

Supabase: `scans/{scan_id}/video.mp4` (+ `poses.jsonl`, `capture.json`, `thumb.jpg`), fetched with `tools/fetch_scan.py`. Scans are also in **Files → On My iPhone → Mint**. See [HANDOFF.md](HANDOFF.md) for the file formats.
