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
