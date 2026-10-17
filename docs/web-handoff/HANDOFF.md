# Web hand-off: buyer and seller sites

Date: Sat Oct 17 2026. Author: Abhinav (role D), with Claude Code as the orchestrator.
Branch: `Abhinav-Multiagent` (local name `ba/two-sites`). Not merged into `main`.

Read this file first. Then read `plan/PLAN.md`. The other files in `plan/` hold the detail.

## 1. What the user asked for

Two web apps share one landing page. The landing looks like Amazon or Facebook Marketplace: a logo, a search box,
and rows of suggested items. A **Sell an item** button sits at the top. There is no auth. The buyer and the seller
are the same demo person (`sel_raj`, "Raj S.").

Seller side:

1. **Your listings**: every past product, with images, price, status, and how it sold.
2. **New listing**: a waiting screen for the iPhone app, then live phone status (connected, uploading), then a
   processing screen while the agents work.
3. **Editor**, from the user's paper sketch:
   - top left: a big 3D view of the splat
   - top right: the name, the suggested price in grey, then a `$` box for the seller's own price
   - below: the description
   - below that: a row of tiles, first "3D", then 2 or 3 real photos
   - bottom right: a small secondary button and **Publish**
4. **Publish** puts the listing on the site.

Buyer side:

1. Every card shows a static photo. On hover it shows the `.spz` splat spinning in 3D. Below the image: title,
   price, and a fair-price rating.
2. The listing page has the same layout as the editor. Instead of Publish it has **Contact seller** (phone and
   email) and **Scan** (the buyer rescans the item).
3. After the rescan, a page shows how well the item matches the listing, with a before/after slider.

Scope rules from the user: frontend only, no backend changes, test with mock data.

Two facts the user asked about:

- The fair-price rating comes from the LISTING (seller) agent's `reference_price_cad`, compared with the asking
  price in `buyer/lib/price-badge.ts`. The buyer agent does not compute it.
- The buyer agent already returns one JSON object (`CompareResponse`, see `multiagent/buyer_agent/models.py`). Its
  "explanation" is a few text fields inside that JSON. The site uses the structured fields.

## 2. How to run it

You need both apps running. The buyer app serves the whole site. It forwards every `/sell/...` URL to the seller app.

```bash
cd seller && pnpm install && pnpm dev          # port 3001, serves /sell/...
cd buyer  && pnpm install && pnpm dev          # port 3000, open http://localhost:3000
```

- Open `http://localhost:3000`, never `:3001`. The two apps share browser storage only on one origin.
- If the seller app runs on another port, start the buyer app with `SELLER_ORIGIN=http://localhost:<port>`. The
  buyer reads this value at start and at build time. After a change, restart it.
- Demo mode: add `?mock=1` to any URL. It stays on (stored in localStorage `mint.mock`). A "Demo data" pill with
  **Turn off** shows in both headers. `?mock=0` turns it off.
- Checks: `pnpm check` in each app (typecheck, lint, unit tests).
- Demo images: `buyer/public/demo/` (real gsplat scans) is tracked. `buyer/public/local/` (PASLCD photos and the
  match page's before/after images) is git-ignored, because the PASLCD licence is not verified. On this branch it
  is TEMPORARILY tracked (commit `77cd7d2`) so a teammate's machine has it. Remove it before any merge to `main`:
  `git rm -r --cached buyer/public/local`. To rebuild the images, run
  `multiagent/.venv/Scripts/python.exe -I buyer/scripts/make_demo_assets.py` (it needs local-only data).

## 3. Where things stand

Test results at the hand-off commit: buyer 187 tests pass (23 files), seller 88 tests pass (8 files). Typecheck and
lint pass in both (one old lint warning in `buyer/components/FilterBar.tsx`).

The orchestrator looked at each screen in a browser. The screenshots are in `shots/`.

| Screen | URL | File(s) | State |
|---|---|---|---|
| Landing | `/` | `buyer/app/page.tsx`, `buyer/components/JustListed.tsx`, `buyer/components/ListingCard.tsx`, `buyer/components/CardMedia.tsx` | Works. Rows: Recommended, Great deals, Garage sales, Fresh scans grid. "Just listed" shows listings published in this browser. Live Supabase listings appear first. See `shots/1-landing.png`. |
| Header | all pages | `buyer/components/SiteHeader.tsx`, `seller/components/SiteHeader.tsx` | Works. Sell an item, Demo data pill. |
| Buyer listing | `/listing/{id}` | `buyer/app/listing/[id]/page.tsx`, `buyer/components/LocalListing.tsx` (exports `ListingView`), `buyer/components/ContactSeller.tsx` | Works, follows the sketch. Tiles, Contact seller, Scan. Reserve and seller card kept. See `shots/2-listing.png`. |
| Your listings | `/sell` | `seller/app/page.tsx`, `seller/components/ListingRow.tsx` | Works. 2 listed, 1 reserved, 2 sold, plus "Scanned, listing not written yet". Small bug: **New listing** shows twice (header and page). See `shots/3-sell.png`. |
| Scan flow | `/sell/scan/new` -> `/sell/scan/{uuid}` | `seller/app/scan/[id]/page.tsx`, `components/ScanFlow.tsx`, `components/PhoneRing.tsx`, `lib/scan-feed.ts`, `lib/progress.ts` | Works in demo mode. Mirrors the iOS app (mint ring, % and "SENDING"). See `shots/5-scan.png`. |
| Editor | `/sell/listing/{id}` | `seller/app/listing/[id]/page.tsx`, `seller/components/ListingEditor.tsx` | Works, follows the sketch. Save draft and Publish write the browser store. In demo mode it replays the real ThinkPad listing (scan `a6816dfc`) with its real `.spz` (done on `sajan/web`, see `PROGRESS.md`). See `shots/4-editor.png`. |
| Rescan + match | `/listing/{id}/check` -> `/listing/{id}/check/{cid}` | `buyer/app/listing/[id]/check/`, `buyer/components/CheckFlow.tsx`, `CompareResult.tsx`, `WipeSlider.tsx`, `SplatWipe.tsx`, `buyer/lib/compare.ts` | Works in demo mode with real recorded agent runs. Verdict in plain words, flagged views, claims (seen, not seen, cannot check), image wipe slider. The 3D splat wipe (`SplatWipe`) needs a buyer splat. No buyer splat exists yet, so it stays hidden. See `shots/6-check.png`. |

Important: five build agents stopped mid-task at a usage limit. Their code passes all checks, and the screens above
work. They did not finish their own review passes. Phone-width (390 px) layouts are not yet checked by a human.

## 4. What to do next (in this order)

1. **Use the real scans in demo mode.** (Done on `sajan/web`: see `PROGRESS.md`.) Nikhil pushed real data after the build started:
   - `.spz` files: `gsplat/out/{backpack,chair,phone,merged,live_check}/splat.spz` (2.3 to 3.0 MB each)
   - real end-to-end runs: `gsplat/out/scan_*/listing.json` and `scan.json` (a ThinkPad mouse scanned on the phone,
     listed by the listing agent)
   - Supabase is live: `assets/listings/index.json` holds 5 listed scans with `splat_url` and 24 spin frames.

   Make the demo use them. Point the mock scan result (`seller/mock/scan-result.json`, built by
   `buyer/scripts/gen-mock.mjs`) at one real `listing.json`. Serve its `.spz` (copy it under `buyer/public/demo/` or
   use the live `splat_url`). Then the sample splats (`SAMPLE_SPLATS` in `lib/mock-mode.ts`) are needed only as a
   last fallback. Never write listing text by hand.
2. **Live phone flow.** The `scan-session` and `scan-upload` edge functions now answer. Test a real scan from the
   iPhone app against `/sell/scan/{uuid}` on `http://localhost:3000` (the QR code encodes `mint://scan?id=<uuid>`).
   The live logic lives in `lib/scan-feed.ts` (`watchScan`, reducer `reduceScan`).
3. **Fix the small bugs:**
   - `seller/app/scan/new/route.ts` drops `?mock=1` on its redirect. Demo mode still works, because the flag
     is stored. Keep the query string anyway.
   - Remove the second **New listing** button on `/sell`.
4. **Check every screen at phone width** (390 x 844) and with the keyboard only.
5. **End-to-end test** (Playwright, `buyer/e2e/`) for the demo walk-through: landing, Sell an item, New listing,
   Skip to result, edit the price, Publish, the item shows in "Just listed", open it, Contact seller, Scan, Skip
   to result, drag the slider.
6. **Live buyer check is not wired** (backend, not frontend). Nothing writes `assets/comparisons/{id}.json` yet.
   In live mode the check page stops at "Comparing with the listing" and says so. The plan for the backend link is
   in `multiagent/` (Abhinav's lane).

## 5. Rules that keep this working

- **Two zones, one origin.** Links between the buyer app and the seller app MUST be plain `<a href>`. A
  `next/link` across zones does nothing. Inside one zone, `next/link` is fine (the seller app adds `/sell` itself). Except links to a route handler that
  redirects (`/sell/scan/new`, `/listing/{id}/check`): plain `<a>` there too, or the client router sometimes drops the
  click (found by the e2e; `NEW_SCAN_HREF` in `seller/lib/scan.ts`).
- **Twin files.** These exist in both `buyer/` and `seller/` and must stay identical after line 1 (line 1 names the
  twin): `lib/local-listings.ts`, `lib/mock-mode.ts`, `lib/compare-types.ts`, `lib/listing-doc.ts`,
  `lib/scan-feed.ts`, `lib/progress.ts`, `lib/splat-scene.ts`, `lib/viewer-slots.ts`, `components/ScanFlow.tsx`,
  `components/PhoneRing.tsx`, `components/SplatViewer.tsx`, `components/MediaPanel.tsx`. Change both copies.
- **Browser store.** Published and draft listings live in localStorage `mint.listings.v1`. Never reuse `mint.v1`.
  The buyer's `lib/store.ts` owns it and drops unknown fields.
- **3D.** All three.js and Spark code sits behind `lib/splat-scene.ts` and loads only in the browser. At most two
  live 3D views at once (`lib/viewer-slots.ts`), because browsers limit WebGL contexts. Before you dispose a
  splat, wait until it is not sorting and is initialised. Otherwise Spark throws unhandled errors.
- **Media API.** `components/MediaPanel.tsx` exports `MediaProvider`, `MediaViewer`, `MediaTiles` and a default
  `MediaPanel`. The page puts the viewer and the tiles in different places of the layout. The provider holds the
  selected tile.
- **Phone links** match Sajan's app (`scanner/DASHBOARD.md`): `mint://scan?id=<uuid>` for a listing,
  `mint://verify?id=<uuid>&listing=<listing scan id>` for a buyer rescan. Always show the QR code.
- **Honest data.** Real agent output only. Never show `evidence_score` or `p_present` as numbers, and never show a
  "% match". Label demo data. The sample splats always carry "Sample 3D, not this item".
- **Git.** Work on `Abhinav-Multiagent` or a new branch. Never push to `main`. Open a PR. Do not add AI attribution
  lines to commits.

## 6. Files in this folder

- `plan/PLAN.md`: the locked plan (decisions, interfaces, task split).
- `plan/PLAN_UX.md`: every screen, state, phase signal and copy line.
- `plan/PLAN_TECH.md`: the proof that zones, the 3D viewer and the splat wipe work. It names a scratch folder on
  Abhinav's machine. That folder is not in the repo. Its code is already copied into the apps.
- `plan/AGENT_RULES.md`: the rules the build agents followed. Ports 3300 and 3301 were a shared preview on
  Abhinav's machine. Use your own.
- `plan/CONTEXT.md`: the first brief, with the user's words.
- `shots/`: screenshots of each screen at 1280 px wide, in demo mode.
