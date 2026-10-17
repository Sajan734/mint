# PLAN_UX: buyer + seller frontends (two zones, one landing)

Frontend only. "Unverified" marks a claim I did not check in code.

## 0. Decisions

- **One origin, two zones (the leaning holds).** Buyer :3000 is the entry. Seller gets `basePath: "/sell"`. Buyer
  rewrites `/sell` and `/sell/:path*` to :3001. Cross-zone links are `<a>`, never `<Link>`
  (`next/dist/docs/01-app/02-guides/multi-zones.md`, "Linking between zones").
- **basePath bug:** `seller/app/scan/new/route.ts:6` builds `new URL("/scan/...", req.url)` and drops `/sell`.
- Seller pages use buyer-zone files (`/frames/...`, `/local/...`). This works only on the shared origin.
- **Mock switch:** `?mock=1` or `?mock=0` on any page sets localStorage `mint.mock` (shared by both zones). While on,
  both headers show a "Demo data" pill with "Turn off". Default off. No env change (root `.env.example` is out of scope).
- **Shared store:** localStorage `mint.listings.v1`, module `lib/local-listings.ts`, identical in both apps. The buyer
  key `mint.v1` (`buyer/lib/store.ts:6`) stays separate.
- **Demo seller:** `sel_raj`, sale `gs_agincourt_tech`, the values live scans use (`gsplat/mintsplat/market.py:27-31`).
  All 5 `sel_raj` mock items are `available` with no orders (§5).

## 1. Routes and flow

| Zone | URL | File | Screen |
|---|---|---|---|
| buyer | `/` | `buyer/app/page.tsx` | Landing |
| buyer | `/listing/{id}` | `buyer/app/listing/[id]/page.tsx` | Listing page |
| buyer | `/listing/{id}/check` | `.../check/route.ts` (new) | New comparison id, redirect |
| buyer | `/listing/{id}/check/{cid}` | `.../check/[cid]/page.tsx` (new) | Rescan, then result |
| buyer | `/saved` `/orders` `/sale/{id}` `/seller/{id}` `/about` | unchanged | |
| seller | `/sell` | `seller/app/page.tsx` | Your listings |
| seller | `/sell/scan/new` | `seller/app/scan/new/route.ts` | New scan id, redirect |
| seller | `/sell/scan/{id}` | `seller/app/scan/[id]/page.tsx` | Scan flow |
| seller | `/sell/listing/{id}` | `seller/app/listing/[id]/page.tsx` | Editor |

Flow:
1. `/`, then **Sell an item** to `/sell`, then **New listing** to `/sell/scan/{id}`.
2. Editor, then **Publish**, then the success panel.
3. **View listing** to `/listing/{id}`, then **Scan** to `/listing/{id}/check/{cid}`, then the result.

States:
- Landing: normal, no search hits (existing, `page.tsx:86`). "Just listed" hides with an empty store.
- Dashboard: normal, empty.
- Scan flow: waiting, connected, uploading, processing, ready, rejected, failed. Hints: "Still waiting for your phone"
  (10 min, no signal), "This is taking longer than usual" (5 min, no change).
- Editor: loading, not found, still working, rejected, failed, draft, invalid input, saved, published.
- Listing page: normal, local, local but missing on this device, sold or reserved (existing, `page.tsx:58`).
- Result: done (any verdict), failed, live not connected (§3), photos missing (§8).

## 2. Screens

### 2.1 Landing `/` (buyer)
- **Header:** logo left. Search always visible (today it hides on home, `buyer/components/SiteHeader.tsx:43`). Nav:
  Saved, Orders, How it works. Right: **Sell an item** (`btn-primary`, `<a href="/sell">`). Mobile: logo and button
  on row 1, search on row 2.
- **Hero** (`page.tsx:45-71`): keep, minus its search form.
- **Just listed** (new, client): published local listings, newest first, at most 8.
- **Garage sales near you**, **Fresh scans**, `FilterBar`: unchanged.

**Card (`ListingCard`, same props):**
- 1:1 box with a static `<img>` of `listing.preview_images[0] ?? frames[0]`.
- On hover (fine pointer) or focus, after 250 ms, mount `SplatViewer` with auto-rotate. Fade in on load, unmount on
  leave. One card plays at a time.
- Source: `splat_url`. With null in mock mode, use a sample splat and a "Sample 3D" pill. With null in live mode, no effect.
- Touch or reduced motion: static image only.
- Pills: views count, status ribbon, Save (existing). Add "3D" for splat items.
- Body: price and `PriceBadge`, then the title (2 lines). Remove description, condition pill, Reserve button and seller
  footer (`ListingCard.tsx:58-76`). This is the user's "title, price, fair-price rating".

### 2.2 Dashboard `/sell`
- "Your listings", then "Raj S. · Agincourt". Right: **New listing** (`<Link href="/scan/new">`).
- Count chips: Drafts, Listed, Reserved, Sold (zeros hidden).
- Rows: thumbnail, title, price, `PriceBadge`, status pill, date, source tag (§5).
- Empty: "Nothing listed yet. Scan something to sell it." and **New listing**.

### 2.3 Scan flow (both kinds)
One `ScanFlow` component, kinds `listing` and `check`. Same two columns as today (`seller/components/ScanSession.tsx:71-142`).
- Left: QR and "On your iPhone? Open the Mint app" while waiting (existing). Phone icon and bar for connected and
  uploading. Spinner, then spin frames, for processing (existing).
- Right: steps Waiting, Phone connected, Uploading, Processing (sub-steps), Ready.
- Mock: banner "Demo: no phone needed. This replays a recorded result." and "Skip to result".
- Listing ready: go to the editor after 1.5 s (existing, `ScanSession.tsx:63-67`). Check ready: result on the same URL.

### 2.4 Editor `/sell/listing/{id}` (the user's sketch)
Grid at md+: left 7/12, right 5/12. One column on mobile.
- **Top left:** big `MediaPanel` viewer (`.spz`, else spin frames).
- **Top right:** NAME (title input). "Suggested price $30" in `text-ink-2`. Under it `$ [____]` "Your price",
  prefilled with the suggested price, with a live `PriceBadge` against `reference_price_cad`. Then "Why this price?"
  (`price_justification`) and "Condition: Light wear". For `needs_seller_check`, the amber note (existing,
  `seller/app/listing/[id]/page.tsx:59-68`).
- **Below:** Description textarea.
- **Below:** 4 tiles: "3D", then `preview_images[0..2]`. A click shows the tile in the big viewer.
- **Bottom right:** **Save draft** (small, `btn-secondary`) and **Publish**.
- Validation: title 1-120 characters, description not empty, price a whole number ≥ 1 (`buyer/lib/schema.ts:15`).
  On error, show the message under the field and focus it.
- Publish saves `state: "published"` with the edited title, description and `price_cad`. Nothing edits
  `reference_price_cad`, so the badge stays honest. Panel: "Published on this device." with **View listing**
  (`<a href="/listing/{id}">`) and **Back to your listings**.
- Data: store entry first (`getLocal(id)`). Else the server reads `assets/listings/{id}.json` (`page.tsx:17`) and the
  client saves it as a draft. Rejected, failed and missing keep today's copy (`page.tsx:20-32`).

### 2.5 Listing page `/listing/{id}` (buyer, like the editor)
- Same grid. Left: `MediaPanel`. With no splat, the 3D view is the existing `SpinViewer`. The e2e slider check needs
  it (`buyer/e2e/buyer-flow.spec.ts:34`).
- Right: title, location, big price, `PriceBadge size="lg"`, "Why this price?", description.
- Bottom right: **Contact seller** (`btn-secondary`) and **Scan** (`<Link href="/listing/{id}/check">`). Helper: "Got
  the item? Scan it to compare with the seller's scan."
- **Contact seller** opens a panel: email (`mailto:`), phone (`tel:`), "Demo contact details". Add optional `email`
  and `phone` to `Seller` (`buyer/lib/types.ts:45`, SellerSchema). Use `@example.com` and 555-01xx numbers (reserved
  fictional ranges) in `mock/sellers.json`. This replaces "Message (demo)" (`page.tsx:106-108`).
- Keep below: Reserve, trust section, seller card, attributes, related grids. E2e and orders use Reserve
  (`buyer-flow.spec.ts:64-70`).
- **Local listing:** `getListing` returns null (`page.tsx:47`). Render client `LocalListing`, not `notFound()`. Not
  in the store: "This listing was published on another device." and **Back to Mint**. Unknown ids need dynamic params
  (Next default, re-check the v16 docs).

## 3. Scan phases and signals

Realtime channel `batch:{id}` (`supabase_setup/storage.py:69-76`). Batch id = scan id (`gsplat/app.py:134`).

| Phase | LIVE signal | MOCK |
|---|---|---|
| waiting | none yet | 3 s |
| connected | first `capture_progress` (proposed) | 2.5 s |
| uploading | `capture_progress`, `status: "uploading"`, `upload_pct` (proposed) | 3 s, bar 0-100 |
| processing | first `stage` event, or `assets/splats/{id}.json` (2 s poll, `ScanSession.tsx:41-59`) | sub-steps |
| ready, listing | `assets/listings/{id}.json`, `status: listed` | `seller/mock/scan-result.json` |
| ready, check | `assets/comparisons/{cid}.json` (proposed, no producer) | recorded `CompareResponse` |
| rejected | document `status: rejected`, reason `rejection.match_check.reason` | `?outcome=rejected` |
| failed | document `status: failed`, or Realtime `error` (`gsplat/app.py:151`, not handled today) | `?outcome=failed` |

Sub-steps by stage prefix (`seller/lib/progress.ts:13`, `gsplat/app.py:143-147`): `1_frames` "Reading the video",
`2_masks` "Finding the item", `3_poses`/`3b_register` "Working out the angles", `4_train` "Building the 3D model",
`5_clean_export`/`6_views` "Cleaning up". Then `7_listing` "Writing your listing", or "Comparing with the listing" for
checks. Mock listing: 900 ms per step. Mock check: the run's real `timings_ms` drive "Comparing views", "Checking the
listing's claims" and "Writing advice".

**Phone-connected signal (for role C).** Reuse `capture_progress`. It is in `contracts/realtime_event.schema.json:14`
with payload `{scan_id, coverage_pct, segments_filled[]}` (`ARCHITECTURE.md:303`). Add optional `status`
(`connected`, `recording`, `uploading`) and `upload_pct`. On `mint://scan?id=...`, the app sends `connected`. This
additive change needs the §7.3 ack. Open: the app needs the anon key, or a relay in the `scan-upload` Edge Function.

**Graceful skip.** The UI never waits for `capture_progress`. A later signal ticks the earlier steps at once.

**Live check is not wired.** It needs `mint://scan?id={cid}&mode=check&listing={id}`. The pipeline must skip
`7_listing`, run the buyer agent and publish `assets/comparisons/{cid}.json` (owners A, C, D). Until then, live mode
stops at "Comparing with the listing". Copy: "The comparison service is not connected yet. Try demo mode (?mock=1)."

## 4. How it matches (`CompareResponse`, `multiagent/buyer_agent/models.py:196-208`)

Never show `evidence_score` or `p_present` as numbers. `evidence_score` is ordinal (`models.py:153`). No "% match".

1. **Heading** from `verdict.label`:

   | label | heading |
   |---|---|
   | same | Looks like the same item |
   | different | Does not match the listing |
   | uncertain | We cannot tell |
   | alignment_failed | The two scans do not line up |
   | scan_quality_poor | Your scan is not clear enough |
   | listing_rejected | The listing scan cannot be used |
   | (status failed) | The check did not finish, then `error.message` and **Try again** |

2. **How sure:** `explanation.how_sure`. 4 of 7 recorded runs have no `explanation`. Then omit it.
3. **Compared:** "{usable_views} usable views of {requested_views}", plus "{n} failed" for non-empty `failed_views`.
4. **What looks different:** one row per `evidence.flagged` category. part_diff "A part looks different or missing",
   color_diff "Colours look different", shape_diff "The shape looks different", any_diff "Something looks different".
   Add "in {categories[c].views.length} of {usable_views} views" and view chips. A chip moves the slider.
5. **What the listing says** (`claims_findings`): supported ✓ "Seen in your scan", contradicted ✗ "Not seen in your
   scan", unverifiable (dash icon) "Cannot check from a scan". Claim text and views. Icon and word, never colour only. For
   `claims_available: false`: "The listing has no claims to check."
6. **Compare views:** `WipeSlider` per pair. Left "Listing" (`a_NN`), right "Your scan" (`b_NN`). Native range input
   for the keyboard. Thumbnail strip below, flagged views marked with a coral dot and their words. **Mapping:** file
   `a_NN` = label `view_{NN+1}` (`multiagent/buyer_agent/pipeline.py:139` saves by 0-based index,
   `runs/fc4b95cb.../jev/view_00.json` holds `"view_01"`).
7. **3D side by side:** both the listing `splat_url` and `assets/splats/{cid}.json` must exist. Two `SplatViewer`s.
   Hidden in mock (no buyer splat).
8. **Next step:** `next_step.summary`, `message_to_seller` with **Copy message**, "Drafted by AI" for
   `is_template: false`, **Contact seller**.
9. **Caveats:** `verdict.caveats` and `explanation.disclaimer`.
10. **Mock footer:** "Recorded result" pill, "Run 435e1251 · 5.0 s" (`timings_ms.total`). For non-pots listings:
    "This recorded check is from a different item (a plant shelf)."

## 5. Dashboard data

Merge and dedupe by id (local, then live, then mock):
- **Mock:** `seller/mock/my-listings.json`, an exact copy of the 5 `sel_raj` entries (itm_0026-0030) in
  `buyer/mock/listings.json`. A seller test reads `../buyer/mock/listings.json` and checks they match.
- **Live:** `assets/listings/index.json` (parse like `buyer/lib/data/live.ts:13-21`), `seller_id == sel_raj`. 404 today.
- **Local:** store entries.

| Shown | Source |
|---|---|
| Status | Local draft: "Draft". Else `market.status`: "Listed", "Reserved", "Sold". |
| Sale info | Orders with this `item_id` in `buyer/mock/orders.json` (none for raj) and the buyer's `mint.v1` orders (same origin): "Reserved · pickup {slot}" or "Sold for {total_cad}". Else "No offers yet". |
| Date | "Saved" + `updated_at` for drafts, else "Listed" + `listed_at`. |
| Source | "Demo data", "Live", "On this device". |
| Action | Draft: **Finish listing**. Local: **Edit**, **View**. Others: **View** (`<a>`). |

A buyer-side reservation in this browser shows how it sold. Option: demo seller `sel_priya` has 2 sold items and 1
reserved, but live scans post as `sel_raj` (`market.py:28`). Orchestrator decides.

## 6. Components

"Both" = identical copy in each app (they cannot import each other). Line 1 of each copy names its twin.

| Component or module | App | Status | Notes |
|---|---|---|---|
| `lib/local-listings.ts` | both | new | `LocalListing {id, state, source, suggested_price_cad, market: MarketListing, created_at, updated_at, published_at?}`. `getLocal`, `upsertLocal`, `useLocalListings()` (useSyncExternalStore, like `buyer/lib/store.ts:53-75`). |
| `lib/mock-mode.ts` | both | new | `useMockMode()`, `SAMPLE_SPLATS`, `sampleSplatFor(id)`. |
| `lib/progress.ts` | both | seller changed, buyer copy | Adds `connected`, `uploading`, sub-step labels. |
| `lib/scan-feed.ts` | both | new | `watchScan(id, kind, mock, onState)` returns unsubscribe. The one live/mock seam. Own minimal types. |
| `components/ScanFlow.tsx` | both | new | Replaces `seller/components/ScanSession.tsx`. |
| `components/SplatViewer.tsx` | both | new | Spark `SplatMesh` + three, as `gsplat/viewer.html:28-60`. `next/dynamic`, `ssr:false`. Props `{url, autoRotate?, interactive?, sample?}`. |
| `components/MediaPanel.tsx` | both | new | Viewer + 4 tiles. Props `{title, splatUrl, photos, sample?, fallback3d: ReactNode}`. |
| `PriceBadge.tsx`, `lib/price-badge.ts` | both | buyer copied to seller | |
| `components/SiteHeader.tsx` | each | changed | Buyer: search, **Sell an item**. Seller: **New listing**, "Back to Mint" `<a>`. Both: "Demo data" pill. |
| `ListingCard.tsx`, `CardMedia.tsx` | buyer | changed, new | §2.1 |
| `JustListed`, `LocalListing`, `ContactSeller` | buyer | new | |
| `CompareResult`, `WipeSlider`, `lib/compare.ts` | buyer | new | `CompareResponse` type, word maps, run loader. |
| `ListingEditor`, `ListingRow` | seller | new | |
| `Spin.tsx` | seller | unchanged | Editor `fallback3d`. |

New dependencies: `three@0.180.0`, `@sparkjsdev/spark@2.1.0`, `@types/three` (both). `@supabase/supabase-js@2.45.4`,
`qrcode@1.5.4`, `@types/qrcode` (buyer, versions from `seller/package.json`).

## 7. Copy (buttons and states)

| Buttons | States |
|---|---|
| `Sell an item`, `New listing`, `Finish listing` | `Scan this code with your iPhone` |
| `Edit`, `View`, `Save draft`, `Publish` | `Phone connected. Walk slowly around the item.` |
| `View listing`, `Back to your listings` | `Uploading your scan…`, `Your listing is ready` |
| `Contact seller`, `Scan`, `Copy message` | `We cannot list this one`, `Something went wrong on our side` |
| `Try again`, `Scan again`, `Start over` | `Saved`, `Copied`, `Published on this device.` |
| `Turn off` | `Demo data`, `Recorded result`, `Sample 3D, not this item` |

## 8. Mock data (real files only)

- **Scan result:** `seller/mock/scan-result.json` = the `pots_i1` entry of `buyer/mock/listings.json`. Its listing
  comes from `multiagent/mock/listings/pots_listing.json` (`buyer/scripts/gen-mock.mjs:91`), likely real listing output
  (unverified, "real" price at `:69`). At runtime override only wrapper fields, as `market.py:99-117` does: `item_id` =
  scan id, `sel_raj`, `gs_agincourt_tech`, Agincourt, `listed_at` = now. `splat_url` stays null.
- **Photos:** `/local/pots/f00-f23.webp` are real PASLCD photos from `buyer/scripts/make_paslcd_frames.py`, in the
  gitignored `buyer/public/local/`. Thumbnails: `f06`, `f12`, `f18`. Missing file: "Photo not on this machine".
- **Compare results:** exact copies of `multiagent/runs/{run}/response.json` as `buyer/mock/compare/{run8}.json`:
  `435e1251` (default: supported, contradicted and unverifiable claims, has `explanation`), `fc4b95cb`, `cce6fb01`
  (zen). `pots_i1` and pots publishes use 435e1251, `zen_i1` uses cce6fb01, others 435e1251 with the note.
- **View pairs:** extend `make_paslcd_frames.py` to write each `a_NN.png`/`b_NN.png` (1024×576, ~1 MB) as 960 px WebP
  q80 to `buyer/public/local/compare/{run8}/`. Gitignored like the hero frames (PASLCD licence unverified). Missing:
  "Comparison photos are not on this machine. Run python buyer/scripts/make_paslcd_frames.py."
- **Sample splats:** sparkjs.dev `butterfly`, `penguin`, `robot-head`, `cat`, `fireplace` `.spz`. Mock mode only,
  always with the pill.
- Mock rejected and failed show UI copy only (fallback at `ScanSession.tsx:125`). No invented reasons.

## 9. Work split (one agent per task, disjoint files)

| # | Task | Owns (exclusively) | Needs |
|---|---|---|---|
| T1 | Foundation | `buyer/next.config.ts`, `seller/next.config.ts`, `seller/app/scan/new/route.ts`, both `package.json` + `pnpm-lock.yaml`, both `lib/local-listings.ts` and `lib/mock-mode.ts`, both `components/SiteHeader.tsx`, `seller/lib/types.ts` (full `MarketListing`), their tests | none |
| T2 | Scan flow | both `lib/progress.ts`, `lib/scan-feed.ts`, `components/ScanFlow.tsx`, plus `seller/app/scan/[id]/page.tsx`, delete `ScanSession.tsx`, `seller/mock/scan-result.json`, `seller/tests/progress.test.ts`, scan-feed tests | T1 |
| T3 | 3D, media, card | both `components/SplatViewer.tsx`, `components/MediaPanel.tsx`, plus `buyer/components/ListingCard.tsx`, `CardMedia.tsx`, `buyer/tests/components.test.tsx` (Reserve checks `:42-46`) | T1 |
| T4 | Seller pages | `seller/app/page.tsx`, `seller/app/listing/[id]/page.tsx`, `seller/components/{ListingEditor,ListingRow,PriceBadge}.tsx`, `seller/lib/price-badge.ts`, `seller/mock/my-listings.json`, tests, `seller/README.md` | T1, T2, T3 |
| T5 | Buyer landing + listing | `buyer/app/page.tsx`, `buyer/app/listing/[id]/page.tsx`, `buyer/components/{JustListed,LocalListing,ContactSeller}.tsx`, `buyer/lib/types.ts`, `buyer/lib/schema.ts`, `buyer/mock/sellers.json`, tests | T1, T3 |
| T6 | Check + result | `buyer/app/listing/[id]/check/**`, `buyer/components/{CompareResult,WipeSlider}.tsx`, `buyer/lib/compare.ts`, `buyer/mock/compare/*.json`, `buyer/scripts/make_paslcd_frames.py`, tests | T1, T2, T3 |

Order: T1 first (short, mostly interfaces). Then T2-T6 in parallel against the §6 signatures. Last, one pass on
:3000 with `?mock=1` over the full flow, and `pnpm check` in both apps. Tests first: `local-listings`, the
`scan-feed` reducer (skip rule, `error` event), `compare` maps and view mapping, editor validation.
