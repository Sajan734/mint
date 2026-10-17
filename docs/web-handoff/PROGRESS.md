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
