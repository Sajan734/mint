# Mint scanner (Role C capture)

The iOS app that captures a full-coverage scan of an item. The plan, decisions and chunks are in [PLAN.md](PLAN.md); what reconstruction receives is in [HANDOFF.md](HANDOFF.md); the role spec is in [role-C.md](role-C.md).

```
scanner/
  ios/
    project.yml                  XcodeGen config → Mint.xcodeproj (generated, not committed)
    Mint/                        the app: camera, coverage ring, tap to focus, recorder, uploader
    Packages/CoverageKit/        pure, unit-tested pieces (pose maths, file formats, fast sharpness, and the
                                 measured-but-shelved tracking work: hull, paper tracker)
  android/                       the same app for Android (Kotlin, Compose, ARCore): app/ + coveragekit/ (the Kotlin port
                                 of CoverageKit's paper read, turn coverage, sharpness and file formats, with its tests)
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

## Run it on an Android phone

Same app, same screens, same Storage layout ([HANDOFF.md](HANDOFF.md)). Needs a phone with Google Play Services for AR (ARCore).

1. Install **Android Studio** (it brings the SDK and a JDK). Open `scanner/android` and let Gradle sync.
2. On the phone: *Settings → About phone →* tap *Build number* 7 times, then *Developer options → USB debugging → On*. Plug it in and allow the computer.
3. Pick the phone as the run target and press **Run**, or from a shell: `cd scanner/android && ./gradlew :app:installDebug`.
4. First launch asks for the camera and, if needed, installs Google Play Services for AR from the Play Store.

Tests: `cd scanner/android && ./gradlew :coveragekit:test` (the CoverageKit tests, ported). Screens without a scan (design checks, debug builds only): `adb shell am start -n ca.htv11.mint.scanner/.MainActivity --es MintPreview review` (also `ready`, `recording`, `full`, `sending`, `finished`, `failed`, `verify`). Links: `adb shell am start -a android.intent.action.VIEW -d 'mint://scan?id=<uuid>'`.

Differences from iOS: ARCore instead of ARKit (same pose convention: camera-to-world, +x right, +y up, looking along −z, gravity up, metres). Focus, exposure and white balance lock through ARCore's shared Camera2 device; on a phone that can't share its camera, ARCore drives it and `capture.json` says `"exposure_locked": false`. Scans are kept in the app's storage (`Android/data/ca.htv11.mint.scanner/files/scans/`, reachable over USB). **The Android Emulator can't run it live:** current emulator builds give the back camera id 10 (virtual scene) or 1 (emulated), and ARCore only opens camera 0, so the session fails to start. Every screen, link and the dashboard connection work there; scanning needs a real phone.

## Using it (the demo)

Open the scanner from the website's QR code (the app's own waiting screen reads it, or the iPhone Camera app). Put the item on a sheet of paper (the coverage ring measures how far the paper has turned; the app never mentions it), line it up, **tap the item to focus** if it looks soft, and tap **Scan**. Turn the paper slowly clockwise while the ring fills (tap to refocus at any time: focus runs once there and holds; exposure stays locked), then tap to stop. **Scan again** for another pass (flipped over), or **Done** to upload every pass to Supabase with a live progress bar (setup: [supabase/README.md](supabase/README.md)). If sending fails, **Share the files** AirDrops a zip.

## Getting a scan off the phone

Supabase: `scans/{scan_id}/video.mp4` (+ `poses.jsonl`, `capture.json`, `thumb.jpg`), fetched with `tools/fetch_scan.py`. Scans are also in **Files → On My iPhone → Mint**. See [HANDOFF.md](HANDOFF.md) for the file formats.
