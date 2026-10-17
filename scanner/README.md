# Mint scanner (Role C capture)

The iOS app that captures a full-coverage scan of an item. The plan, decisions and chunks are in [PLAN.md](PLAN.md); what reconstruction receives is in [HANDOFF.md](HANDOFF.md); the role spec is in [role-C.md](role-C.md).

```
scanner/
  ios/
    project.yml                  XcodeGen config → Mint.xcodeproj (generated, not committed)
    Mint/                        the app: AR session, dome, HUD
    Packages/CoverageKit/        pure logic (dome segments, sharpness, coverage, guidance) + unit tests
```

## Run it on your iPhone

1. Install **Xcode** from the App Store, open it once, and let it install the iOS platform.
2. `sudo xcode-select -s /Applications/Xcode.app` (so command-line tools use Xcode, not CLT).
3. `cd scanner/ios && xcodegen` (re-run after adding or removing files).
4. `open Mint.xcodeproj` → target **Mint** → *Signing & Capabilities* → tick *Automatically manage signing*, choose your Apple ID team. If the bundle ID is taken, change `ca.htv11.mint.scanner` in `project.yml` and re-run xcodegen.
5. Plug in the iPhone; on the phone: *Settings → Privacy & Security → Developer Mode → On* (it restarts).
6. Pick the iPhone as the run destination, press **⌘R**. First launch: *Settings → General → VPN & Device Management → trust your developer certificate*.

Tests: **⌘U** in Xcode (runs `CoverageKitTests`), or `cd ios/Packages/CoverageKit && swift test`.

## Using it

Move the phone until the coaching overlay finds the table → **tap the item** → a dome of 24 tiles appears around it (pinch to resize). Walk around at two heights; tiles turn mint as sharp, steady frames land. The ring at the bottom is a top-down map (you're the white dot). Exposure, focus and white balance lock when you tap. It finishes by itself at 90% coverage.

## Getting a scan off the phone

When a scan finishes, tap **Send to teammate** (AirDrop the zip). Scans are also in **Files → On My iPhone → Mint**, and in Finder (phone plugged in → Files tab). Check one with `tools/check_scan.py` (see [HANDOFF.md](HANDOFF.md)).
