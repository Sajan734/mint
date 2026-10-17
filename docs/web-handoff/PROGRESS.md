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
