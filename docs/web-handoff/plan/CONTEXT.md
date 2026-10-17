# Context: buyer + seller web apps (frontend only)

Date 2026-10-17. Branch `ba/two-sites` (from main 0b9657f). Repo root `C:\Users\abhin\Downloads\mint`.
Apps: `buyer/` (Next.js 16.4.2, React 19.3, Tailwind 4, pnpm, port 3000) and `seller/` (same stack, port 3001,
a scaffold by teammate Nikhil, PR #9). Read each app's `AGENTS.md`: this Next.js version has breaking changes, so read
the guide in `node_modules/next/dist/docs/` before writing Next-specific code.

Baseline: buyer `pnpm test` 64 passed (13 files), seller 9 passed (1 file). Typecheck and lint pass in both.

## What the user asked for (their words, condensed)

FRONTEND ONLY. No backend work. Test with mock data. No auth, no accounts. Buyer and seller are the same person
for the demo.

1. Two sites (buyer/, seller/) share ONE landing page. It looks like an Amazon or Facebook Marketplace landing:
   company logo, many suggested items. At the top: a "Sell an item" button.
2. Sell button -> seller side, first screen: a list of all your previous products and how they sold (if they
   have): images, description, info, status. At the top of that page: a "New listing" button.
3. New listing -> a waiting screen for the phone app to connect (the phone app takes the scan. Today seller/ shows a
   QR deep link `mint://scan?id={uuid}`). Once connected it takes the scan. Through Supabase (webhook -> pipeline ->
   Realtime events / public files) we learn the scan is uploaded. Then a processing/loading screen while the agents
   work in the background. Then the agents' JSON output arrives (listing doc).
4. Then a listing editor screen, from the user's sketch:
   - top-left: big 3D viewer (the .spz splat)
   - top-right: NAME, "suggested price" in grey, below it a `$ [____]` input for the seller's actual price
   - below: Description (text)
   - below: a row of 4 thumbnails: first is "3D" (the 3D view), then 2-3 held-out photos of the item
   - bottom-right: two buttons, a small secondary one and "Submit/Publish"
   Prefill name, description, suggested price and photos from the agent JSON. Publish posts the listing on the webapp.
5. Buyer view: every listing card shows a static 2D image (a held-out photo). On hover it shows the .spz splat
   spinning in 3D. Below the image: title, price, fair-price rating.
6. Clicking a listing: a page very similar to the seller editor, but instead of Publish there are two buttons:
   "Contact seller" (shows the seller's phone or email) and "Scan" (rescan the object to find defects compared with
   the seller's scan. This is the buyer-side comparison agent).
7. After a buyer scan: a page that shows how much it matches, with a before/after slider over the splats. If a
   slider is too hard, side-by-side.

## Facts the orchestrator verified (cite these, re-check what you rely on)

- seller/ routes today: `/` landing ("Scan an item"), `/scan/new` (route.ts, redirects to `/scan/{uuid}`),
  `/scan/[id]` (QR + `components/ScanSession.tsx`: Realtime channel `batch:{id}` stage events when
  NEXT_PUBLIC_SUPABASE_ANON_KEY is set, plus polling public `assets/splats/{id}.json` then
  `assets/listings/{id}.json` every 2 s), `/listing/[id]` (read-only draft). `lib/progress.ts` maps to phases
  waiting/scanning/writing/listed/rejected/failed. `components/Spin.tsx` = drag-to-turn image frames.
- seller/README says publish and price editing are "not built yet". Today every listed scan appears on the buyer site.
- Pipeline document (`gsplat/mintsplat/market.py`, public): `assets/listings/{scan_id}.json` =
  `{v, scan_id, status: listed|rejected|failed, market_listing?, rejection?, error?, spin_urls?, timings_ms?}`.
  `market_listing` = `{listing (listing/contracts.py Listing), category, reference_price_cad, frames, splat_url,
  usable_view_count, listed_at, seller_id, garage_sale_id, location, status}`. Types in `seller/lib/types.ts` and
  `buyer/lib/types.ts` (buyer's MarketListing is the fuller one, with seller_id and more).
- Supabase public `assets/listings/index.json` and `assets/splats/index.json` return 404 today: NO real scan has been
  published yet. There are NO real product .spz files on this machine.
- Public sample splats work and allow CORS (`Access-Control-Allow-Origin: *`): e.g.
  `https://sparkjs.dev/assets/splats/butterfly.spz` (4 MB), also penguin, robot-head, cat, fireplace. They are not
  products: use them only as clearly labelled placeholders when a listing has no splat.
- 3D viewer used by the team: `gsplat/viewer.html` = three 0.180.0 + `@sparkjsdev/spark` 2.1.0 (SparkRenderer,
  SplatMesh, OrbitControls). npm has `@sparkjsdev/spark` 2.1.0 (peer three >= 0.180.0, dep fflate).
- Fair-price rating: `buyer/lib/price-badge.ts` compares the asking price with `reference_price_cad`, which comes from
  the LISTING (seller) pipeline, not from the buyer agent.
- Buyer agent API (`multiagent/buyer_agent/models.py` CompareResponse) returns one JSON object:
  `{v, comparison_id, status: done|failed, verdict: {label, evidence_score, reason, evidence: {requested_views,
  answered_views, usable_views, failed_views, categories, flagged, alignment, alignment_mode}, caveats},
  claims_available, claims_findings: [{claim, source, status: supported|contradicted|unverifiable, p_present, views}],
  next_step, explanation, error, model_ids, timings_ms, run_id}`. `evidence_score` is ordinal evidence for the
  label, NOT a match percentage. Do not invent a "% match".
- REAL buyer-agent outputs exist: `multiagent/runs/<id>/response.json` (7 runs, all verdict "different"), each with
  the real view images the agent compared: `a_00..a_11.png` (seller/listing side) and `b_00..b_11.png` (buyer side),
  ~1 MB each. These are the honest before/after pairs for a wipe slider. `buyer/mock/verify-sample.json` is a subset
  of run fc4b95cb.
- buyer/ data layer: `lib/data/index.ts` (server accessors), `mock.ts`, `live.ts` (public listings index, falls back
  to mock), `mock/*.json` (40 listings, sellers, garage sales, orders). Existing components include ListingCard,
  SpinViewer, PriceBadge, VerifyItemPanel, SiteHeader, ReserveSheet.
- Ports: buyer 3000, seller 3001. Env `NEXT_PUBLIC_BUYER_URL` (seller -> buyer link) exists in root `.env.example`.
  Both next.config.ts files load the repo-root `.env`.

## Orchestrator's leaning (planners: confirm or overturn with evidence)

- ONE ORIGIN via Next.js multi-zones: buyer at :3000 is the entry. Seller gets `basePath: "/sell"`. Buyer rewrites
  `/sell` and `/sell/:path*` to the seller server. Then the landing page is buyer `/`, the Sell button is `/sell`,
  both zones share localStorage, so a mock "publish" in seller is visible in buyer. Fallback if multi-zones break in
  dev: hand the published listing to the buyer via a URL hash.
- MOCK MODE: one flag (e.g. `?mock=1` or env `NEXT_PUBLIC_MOCK_PIPELINE=1`) replays the scan flow with timers
  (waiting -> phone connected -> uploading -> processing stages -> listing JSON) and the buyer rescan flow (-> a real
  recorded CompareResponse). Live mode keeps the real Supabase Realtime + public-file polling. One module is the seam.
- PUBLISH (mock): writes the edited listing into one shared localStorage store (one module, one key), read by both
  zones. Real publish later swaps this module for an API call. Never claim it is live.
- Same-person demo user: seller id `sel_raj` (gsplat market.py LIVE uses it).
- No backend changes. No edits outside `buyer/`, `seller/` and the design docs folder.
