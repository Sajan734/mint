# Web progress log (branch `sajan/web`)

Picks up from `HANDOFF.md`. Newest last. Test counts are `pnpm check` (typecheck, lint, unit tests).

Baseline (from `origin/Abhinav-Multiagent` + `origin/main`, Oct 17): buyer 187 tests (1 skipped), seller 88. Lint
clean except the old warning in `buyer/components/FilterBar.tsx`.

## A. Real scans in demo mode

- Demo mode's scan flow now replays a real end-to-end run: the ThinkPad mouse scanned on the phone and listed by
  the listing agent (`gsplat/out/scan_a6816dfc/listing.json`, 56 s from upload to listing).
- `python3 -I buyer/scripts/make_demo_assets.py listing` fetches that listing's `.spz`, 4 preview images and 24
  spin frames from Supabase into `buyer/public/demo/listings/a6816dfc/` (3 MB, so demo mode works offline) and
  writes `seller/mock/scan-result.json` from it. Only URLs change; a test checks the text, prices and flags equal
  the agent's file. The script's steps can now run one at a time (`scans`, `listing`, `compare`, `paslcd`), since
  `multiagent/runs/` and the PASLCD inputs are not on every machine. It uses `certifi` for TLS when present.
- `gen-mock.mjs` no longer writes `scan-result.json`.
- Sample splats (`SAMPLE_SPLATS`) are now only used for the generated catalog items, which have no scan.
- Seen at 1280: editor, "Just listed" card hover and the buyer listing page all show the real ThinkPad splat.
- Tests: buyer 187 (1 skipped), seller 88.

## B. Small bugs

- `seller/app/scan/new/route.ts` keeps the query string on its redirect (`/sell/scan/new?mock=1` ->
  `/sell/scan/{uuid}?mock=1`).
- `/sell` shows one **New listing**: the page header's, or the empty state's when there is nothing listed. The site
  header hides its own on `/sell` only (`usePathname() === "/"` inside the `/sell` zone; checked live).
- Seen at 1280 and 390 with demo data on and off. Tests: seller 91 (+3: query string, header, button count).

## C. Phone width, keyboard, iOS look

- Checked at 390 x 844 (Playwright): landing, `/sell`, scan flow (waiting, connected, uploading, done), editor,
  published panel, buyer listing, Contact seller, check flow and result. No horizontal scroll on any of them.
- Keyboard: tabbed through every screen. Every stop has a visible focus ring. Fixes:
  - **Skip to content** link in both apps (first Tab stop, jumps to `<main id="main">`).
  - Logo links are 44 px tall (were 28).
  - Buyer header at 390: logo, demo pill and **Sell an item** now fit one row (8 px gaps on phones).
  - Media tiles are announced "View 1-3", not "Photo 1-3": for real scans they are renders of the splat.
- iOS look (`scanner/ios/Mint/Screens.swift`): the ripples now match the app's (3 thin mint rings a third of a
  cycle apart, 2.4 s, growing linearly and fading, inside a fixed box), behind the QR while waiting and behind the
  check when done. They no longer cross the text. Animation is `animate-mint-ripple` from a `@theme` block (an
  `@theme inline` block leaves the keyframes nested inside `:root`). Ring, numbers and words already matched.
- The seller header at 390 with demo data on still takes 2 rows (logo, Seller, Demo pill do not leave room).
- Dev gotcha: running `next build` in `seller/` while `pnpm dev` runs corrupted `seller/.next` and sent every
  seller page into an endless "HMR hash mismatch" reload. Fix: stop the server, delete `seller/.next`, restart. Also,
  `pnpm build` (Turbopack) fails on this machine inside `next/font/google` ("queries have exactly one entry"),
  before and after these changes; `next build --webpack` builds but has no Tailwind (no PostCSS config).
- Tests: buyer 187 (1 skipped), seller 91.

## D. End-to-end test of the demo walk-through

- `buyer/e2e-demo/walkthrough.spec.ts`, run with `cd buyer && pnpm test:e2e:demo` (`playwright.demo.config.ts`). It
  runs on `http://localhost:3000` with both dev servers (reuses running ones, else starts `pnpm dev` in both apps),
  at 1280 and at 390 wide: landing -> Sell an item -> New listing (QR shown) -> Skip to result -> editor holds the
  real ThinkPad listing -> price 17 -> Publish -> the card is in "Just listed" at $17 -> open it -> Contact seller
  (demo email shown, Escape closes) -> Scan -> Skip to result (says the recorded check is from another item) -> drag
  the before/after slider (value drops) -> ArrowRight moves it by 1. Fails on any page error.
- The existing `pnpm test:e2e` (buyer only, `next build` on :3107) is unchanged; its build fails on this machine (see C).
- Bug it found: **New listing** and **Scan** were `next/link`s to route handlers that redirect; the client router
  sometimes dropped the click (no request at all). They are plain `<a>` now.
- Dev compiles a route on its first visit, so the demo config gives `expect` 30 s. The first run right after editing
  files can still fail while the dev servers rebuild; rerun. Result: 10 of 10 runs pass (desktop and phone) after that.
- Tests: buyer 187 (1 skipped), seller 91, e2e demo 2.

## E. Live phone flow

- `scan-session` and `scan-upload` answer (`{"action":"next"}` -> `{"request":null}`; `scan-upload` validates its
  body). The site never calls `request` (that would make its own scan id and pop the scanner open on the team's
  phone); it shows the QR of its own UUID and polls `status`, which is 404 "no such scan" until the app's first
  `update`. `watchScan` treats that 404 as "the phone has not reported yet".
- Real data, live mode (demo off), no phone: `/sell/scan/a6816dfc-...` sees the published splat manifest and
  listing, saves a draft and opens the editor with the real title, price, flags and the real Supabase `.spz`. No
  demo or sample labels. Seen at 1280 and 390.
- Buyer, live: the real listing page works; **Scan** shows the verify QR `mint://verify?id=<uuid>&listing=a6816dfc-...`.
  Live verify then waits at "Comparing with the listing" (nothing publishes `assets/comparisons/` yet: Abhinav's lane).
- `buyer/e2e-demo/live-phone.spec.ts`: live mode with the phone simulated in the browser (route interception of
  `scan-session` and of the two public files, which it fills with the real `gsplat/out/scan_a6816dfc` run). It checks
  waiting (QR = `mint://scan?id=<this id>`) -> Phone connected (1 pass) -> Uploading 42% (2 passes) -> Building your
  listing -> ready -> editor filled from the listing. Writes nothing to Supabase. Passes at 1280 and 390.
- Still needed: one real scan from the iPhone app against `http://localhost:3000/sell` with demo data off.
- Tests: buyer 187 (1 skipped), seller 91, e2e demo 4 (2 specs x desktop/phone).

## Redesign (branch `sajan/web-design`, from `sajan/web`)

The team found the UI "vibe coded". New design system in `docs/design/DESIGN.md`, built with the taste-skill rules
(`design-taste-frontend`, `redesign-existing-projects`, installed in `~/.claude/skills`) and the Starbucks and Shopify
systems from awesome-design-md.

- Look: a neighbourhood shop. Oat canvas, pine ink, mint-leaf actions, a pine field for deep bands and the footer,
  a mint wash, brand mint ("spark") only on pine. Fraunces (soft) for signs, Figtree for everything else. Full pill
  buttons that press in. No outlined boxes, hairlines, gradients, glows, mono labels, eyebrows or numbered badges.
- Taste audit of the old UI: 57 lint failures, 8 browser failures (mono labels, radial-gradient pads, outlines,
  hairlines, 3 typefaces, text under 13px, no first-screen focal point).
- Landing: split hero led by the real ThinkPad scan you can turn; product grids instead of side-scrolling rails;
  a pine "How Mint works" band with real spin frames; garage sales as a noticeboard; pine footer with the name large.
- Every other screen moved to the system: header, cards and badges, listing page, contact dialog, reserve sheet,
  check flow on a pine phone panel, result page, seller dashboard, editor, sale and About pages. Dark mode follows.
- iOS (`scanner/ios/Mint`): Brand.swift has the same palette and font helpers (New York for big lines, SF Pro for
  text, SF Rounded only for big percentages); sentence-case labels; no glass, glows or gradients; capsule buttons;
  the same seal mark. Builds for the simulator; the waiting screen was checked there (no camera in the simulator
  for the others).
- CSS lesson: base and component rules must sit in `@layer base` / `@layer components`, or Tailwind v4 utilities
  lose to them. Turbopack dev sometimes serves stale CSS after `globals.css` edits: restart `pnpm dev`.
- Tests: buyer 207 (1 skipped; +20 contrast checks in `tests/design-tokens.test.ts`), seller 91, e2e demo 4.

## Theme back to the original, light only (Oct 17)

The team disliked the pine/oat/Fraunces look, mostly in the app. Layouts stay; the theme goes back.

- Web: the original palette (paper `#FAF7F2`, ink `#0B0F0E`, brand mint `#3DDC97`, leaf `#1B6B49` for green text),
  Bricolage Grotesque + Figtree, the original mint mark and wordmark, 14px button corners, ink primary buttons.
  Light mode only: the pine bands and footer are now the light mint wash `#DDF6EA`. Contrast tests cover light only.
- iOS: full-screen moments are light (paper, ink, mint); only the scanner HUD over the camera stays dark.
- Text emphasis and font changes are on hold until the team asks.

## Scanner camera and QR (iOS, untested on a device)

- "Zoomed in": the preview filled the screen and cropped the 4:3 sensor. It now shows the whole 4:3 frame that is
  recorded (letterboxed).
- "Edges blur": ARKit could pick a format on another lens and autofocus hunted during the turn. The session now picks
  the back wide-angle camera at 1920x1440, aims focus and exposure at the item while lining up, and locks focus,
  exposure and white balance when the scan starts (`CameraLock.lock()`).
- QR on another computer: likely a small code in the full 1920x1440 frame. `PaperReader.qrCode` now retries on the
  frame's centre (60%). Root cause not confirmed; needs a try on the phone.

## Real Gaussian splats in the demo catalogue

- 18 downloadable scenes from SuperSplat (superspl.at), CC BY 4.0 (the planter is CC BY-SA 4.0), replace the
  generated items and the old sample splats. Each is a listing with its own title, price, grade and description.
  Credits: About `#credits`, the listing's "3D scan" attribute, and a footer link. `mock/splat-credits.json` lists
  scene, author and licence. Left out: CC BY-NC scenes, LOD scenes (Spark can't read `lod-meta.json`), and sources
  without a licence.
- Streamed live from SuperSplat's CDN (`.../<id>/<v>/meta.json`, CORS open). Spark 2.1 reads SOGS only as a zip, so
  `splat-scene.ts` fetches `meta.json` and its webp textures and zips them in the browser with `fflate` (no
  compression). A `#rx=..&ry=..` fragment sets the scene's rotation; framing uses the 2nd-98th percentile of splat
  centres so stray background splats don't shrink the item.
- Stills: `node buyer/scripts/render-splats.mjs` renders 24 frames per scene at 512px into
  `buyer/public/demo/splats/<key>/` (21 MB) with Playwright on the GPU (`SOFTWARE=1` for SwiftShader, which is far
  too slow for 1M splats). Cards and spin strips use these, so only the 2 live viewers stream splats.
- Landing hero: the Sony Alpha 7 (veryos, CC BY 4.0), linked to its listing. The ThinkPad mouse is no longer the
  headline; it stays as the real end-to-end scan in the seller demo.
- Tests: buyer 195 (1 skipped), seller 91, e2e demo 4.

## Compare result: no view-by-view, binary verdict
- Removed `WipeSlider`, the "Compare views" section, view chips and the `public/local/compare` WebP generation. Only the overall "Both scans in 3D" `SplatWipe` stays; without splats the text column is full width.
- Verdict is strictly `same` or `different`, with optional `cause` (`low_quality`, `misaligned`, `listing_rejected`) shown as a sub-line. "We cannot tell" is gone. A failed check says "Could not run the check, try again" and shows no mark.
