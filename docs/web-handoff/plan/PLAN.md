# PLAN: buyer + seller web apps (frontend only)

Date 2026-10-17. Branch `ba/two-sites` (main 36ffbb1). Status: APPROVED by the user ("plan and implement, lock in").
Sources: CONTEXT.md, PLAN_UX.md (screens, copy, states), PLAN_TECH.md (zones, 3D, tests). This file wins where they
differ. Agents read this file first, then the section of PLAN_UX or PLAN_TECH it points to.

## 1. What we build

One website at `http://localhost:3000`, made of two Next.js apps (zones):
- `buyer/` serves `/` (the shared landing page) and every buyer page.
- `seller/` serves everything under `/sell`. The buyer app proxies `/sell/*` to it.

Flow: landing -> **Sell an item** -> your listings -> **New listing** -> phone hand-off (QR) -> phone scanning ->
uploading -> processing -> editor (sketch) -> **Publish** -> the listing is on the landing page -> buyer listing page
-> **Contact seller** or **Scan** -> phone hand-off -> processing -> "how it matches" with a before/after slider.

Frontend only. No backend, no Supabase or pipeline changes, no auth. Buyer and seller are one demo person, `sel_raj`.

## 2. Decisions (locked)

| # | Decision | Why / source |
|---|---|---|
| Z1 | Multi-zones. Seller `basePath: "/sell"`. Buyer rewrite `/sell/:path*` -> `${SELLER_ORIGIN}/sell/:path*`, `SELLER_ORIGIN` default `http://localhost:3001`, read with `\|\|`. | Proven in dev and prod build (PLAN_TECH §1) |
| Z2 | Links between zones are plain `<a href>`, never `next/link` (a buyer `<Link href="/sell">` silently fails). Seller logo becomes `<a href="/">`. | PLAN_TECH §1 |
| Z3 | Fix `seller/app/scan/new/route.ts`: redirect with a relative `Location: /sell/scan/<id>` (today it drops `/sell`). | PLAN_TECH §1, tested |
| S1 | Shared browser store: `lib/local-listings.ts`, key `mint.listings.v1`, one identical copy per app. Entries are drafts or published listings. Notify same-tab listeners directly (the `storage` event does not fire in the writing tab). Never touch `mint.v1` (buyer `store.ts` erases extra fields when it writes). | PLAN_UX §0, PLAN_TECH §2 |
| M1 | Mock switch `?mock=1` / `?mock=0` on any page, kept in localStorage `mint.mock`. Both headers show a "Demo data" pill with "Turn off" while on. | PLAN_UX §0 |
| P1 | Phone hand-off follows Sajan's app exactly (`scanner/DASHBOARD.md`): listing QR = `mint://scan?id=<uuid>`, buyer rescan QR = `mint://verify?id=<uuid>&listing=<listing scan id>`. The site makes the UUID. Always show the QR. | iOS app `DashboardLink.swift:4-5,69-90` |
| P2 | Live phone status comes from the keyless `scan-session` function (`POST .../functions/v1/scan-session`, `{action:"status", scan_id}`): `waiting` -> `scanning` (passes) -> `uploading` (progress 0..1) -> `uploaded`, or `cancelled`. `scanning` = "Phone connected". It is NOT deployed today (NOT_FOUND), so the UI must work without it: never wait on it, skip steps a later signal proves. | `scanner/supabase/functions/scan-session/index.ts:12-19` |
| P3 | After upload: Realtime `batch:{id}` `stage` events (needs anon key) and polling public `assets/splats/{id}.json`, then `assets/listings/{id}.json` (listed / rejected / failed). Verify results: poll `assets/comparisons/{id}.json` (proposed, NO producer yet). Live verify stops at "Comparing with the listing" with the copy in PLAN_UX §3. | `seller/components/ScanSession.tsx`, listing-link PLAN D7 |
| V1 | 3D = three 0.180.0 + `@sparkjsdev/spark` 2.1.0, behind one module `lib/splat-scene.ts` (dynamic import in `useEffect`, never SSR). Copy the tested files from the tech probe. At most 2 live viewers at once (`lib/viewer-slots.ts`). Dispose only when `!spark.sorting && mesh.isInitialized`. | PLAN_TECH §3, screenshots seen |
| V2 | Card hover: static photo, then after a short dwell mount the splat spinning. No splat: the existing frame spinner. Touch or reduced motion: static only. | PLAN_UX §2.1, PLAN_TECH §6 |
| C1 | Before/after: (a) image wipe over the real view pairs the agent compared (always, in mock and live), plus (c) a true splat wipe (two canvases + clip-path, synced camera) when a buyer splat URL exists. Never show `evidence_score` or `p_present` as numbers. No "% match". | PLAN_UX §4, PLAN_TECH §4 |
| U1 | Mirror the iOS app's look on the phone hand-off screens: mint progress ring (round caps, big rounded % number, "SENDING" caps label), ripples while waiting, mint check circle when done, the same words ("Look back at your computer" -> web "Your phone is done"). Font stack `ui-rounded, "SF Pro Rounded", system-ui` for those numbers. Same brand colours as `scanner/ios/Mint/Brand.swift` (already the web tokens). | `scanner/ios/Mint/Screens.swift:18-263` |
| D1 | Demo data is real files only. Listing text, prices and comparisons come from real agent output: the `pots` listing and the 7 real runs in `multiagent/runs/` (with their `a_NN`/`b_NN` view images). Product imagery comes from Nikhil's real scans in `gsplat/out/` (backpack, chair, phone, merged = ThinkPad mouse, live_check = mouse with 24 spin frames, held-out photo sheets). Their `.spz` files were not committed, so real 3D waits for Nikhil, until then mock mode uses Spark sample splats, always labelled "Sample 3D, not this item". | `gsplat/out/*`, e80f994 |
| D2 | No listing-agent output exists for the 5 real scans (no `listing/runs`). So they are NOT buyer catalog items. They appear on the seller dashboard as "Scanned. Listing not written yet." rows with their real images, and they feed the mock scan flow imagery. They join the catalog when Nikhil or Hurayrah supply their listing JSON. Never invent agent text. | honesty rule, checked on disk |

## 3. Interfaces (T1 writes these exactly, as working code or typed stubs, everyone codes against them)

```ts
// lib/local-listings.ts (buyer + seller, identical)
export const LOCAL_KEY = "mint.listings.v1";
export type LocalState = "draft" | "published";
export interface LocalListing { id: string; state: LocalState; source: "mock" | "live";
  suggested_price_cad: number; market: MarketListing; created_at: string; updated_at: string; published_at?: string }
export function listLocal(): LocalListing[]; export function getLocal(id: string): LocalListing | null;
export function upsertLocal(e: LocalListing): void; export function useLocalListings(): LocalListing[];

// lib/mock-mode.ts (both)
export const DEMO_SELLER_ID = "sel_raj";
export function useMockMode(): boolean; export function isMockMode(): boolean; export function setMockMode(on: boolean): void;
export const SAMPLE_SPLATS: string[]; export function sampleSplatFor(id: string): string;

// lib/compare-types.ts (both): CompareResponse and children, mirroring multiagent/buyer_agent/models.py:150-208
// lib/listing-doc.ts (both): ListingDoc + SplatManifest (from seller/lib/types.ts), MarketListing = buyer's full type

// lib/scan-feed.ts (both) - the ONE live/mock seam
export type Phase = "waiting" | "connected" | "uploading" | "processing" | "ready" | "rejected" | "failed" | "cancelled";
export interface ScanState { phase: Phase; passes: number; uploadPct: number | null; subStep: string | null;
  listing: ListingDoc | null; compare: CompareResponse | null; message: string | null; hint: string | null }
export function watchScan(o: { scanId: string; kind: "listing" | "verify"; listingId?: string; mock: boolean },
  onState: (s: ScanState) => void): () => void;

// components/ScanFlow.tsx (both, client): <ScanFlow kind scanId listingId? deepLink qrSvg onDone?(s: ScanState) />
// components/SplatViewer.tsx (both, client): <SplatViewer src label autoRotate? interactive? poster? className? onLoad? onError? />
// components/MediaPanel.tsx (both, client): <MediaPanel title splatUrl frames photos sample? />  (big viewer + "3D" tile + up to 3 photo tiles)
```

## 4. Work split (all agents share the one checkout, files are disjoint, no agent commits)

| Wave | Task | Model | Owns exclusively |
|---|---|---|---|
| 1 | T1 Foundation | sonnet | both `next.config.ts`, `package.json`, `pnpm-lock.yaml`, `seller/app/scan/new/route.ts`, both `lib/local-listings.ts`, `lib/mock-mode.ts`, `lib/compare-types.ts`, `lib/listing-doc.ts`, both `components/SiteHeader.tsx`, `seller/lib/types.ts`, `buyer/lib/types.ts`, `buyer/lib/schema.ts` (Seller `email?`, `phone?`), typed STUBS of `lib/scan-feed.ts`, `components/ScanFlow.tsx`, `components/SplatViewer.tsx`, `components/MediaPanel.tsx` in both apps, tests for store + mock mode |
| 1 | T7 Demo data | sonnet | `buyer/public/demo/**`, `buyer/scripts/make_demo_assets.py`, `buyer/mock/compare/*.json`, `buyer/mock/sellers.json` (demo email/phone, `@example.com`, 555-01xx), `seller/mock/*.json`, `buyer/mock/listings.json` + `buyer/scripts/gen-mock.mjs` only if adding the 5 real-scan items, `buyer/tests/mock-data.test.ts` |
| 2 | T2 Scan flow | opus | both `lib/scan-feed.ts`, `lib/progress.ts`, `components/ScanFlow.tsx`, `components/PhoneRing.tsx`, `seller/app/scan/[id]/page.tsx`, delete `seller/components/ScanSession.tsx`, `seller/tests/progress.test.ts`, scan-feed tests (both) |
| 2 | T3 3D + media + card | opus | both `lib/splat-scene.ts`, `lib/viewer-slots.ts`, `components/SplatViewer.tsx`, `components/MediaPanel.tsx`, `buyer/components/ListingCard.tsx`, `buyer/components/CardMedia.tsx`, `buyer/tests/components.test.tsx`, viewer tests |
| 2 | T4 Seller pages | opus | `seller/app/page.tsx`, `seller/app/listing/[id]/page.tsx`, `seller/components/{ListingEditor,ListingRow,PriceBadge}.tsx`, `seller/lib/price-badge.ts`, seller page tests, `seller/README.md` |
| 2 | T5 Buyer landing + listing | opus | `buyer/app/page.tsx`, `buyer/app/listing/[id]/page.tsx`, `buyer/components/{JustListed,LocalListing,ContactSeller}.tsx`, buyer page tests, `buyer/README.md` |
| 2 | T6 Check + compare | opus | `buyer/app/listing/[id]/check/**`, `buyer/components/{CompareResult,SplatWipe}.tsx`, `buyer/lib/compare.ts`, compare tests |
| 3 | T8 End-to-end + review | sonnet + reviewers | `buyer/e2e/**`, `seller/e2e/**` (new), reviewers are read-only |

Order: T1 and T7 in parallel. The orchestrator checks T1 (typecheck, lint, tests in both apps, and the zone proxy
answering on :3000/sell) before wave 2. Wave 2 runs T2-T6 in parallel. Then T8 and the reviewers. Fixes go back to
the owning task.

## 5. Rules for every implementation agent

- Read this file, then `buyer/AGENTS.md` / `seller/AGENTS.md` (Next 16 differs: read `node_modules/next/dist/docs/`).
- Edit only the files you own. If you need a change elsewhere, stop and report it.
- Others are editing at the same time. Check with targeted commands only: `pnpm exec vitest run <your tests>`,
  `pnpm exec eslint <your files>`, `pnpm exec tsc --noEmit` (report errors in files you do not own, do not fix them).
- Tests first for pure logic (store, scan-feed reducer, compare word maps, view mapping, editor validation, price badge).
- Real data only. No invented agent output, no lorem ipsum. Missing data shows a plain placeholder.
- Accessibility: real buttons and links, labels, focus states, `prefers-reduced-motion`, 44 px targets, text contrast.
- Keep the existing design tokens (`app/globals.css`). The landing is a dense marketplace grid (Amazon / Facebook
  Marketplace feel), not a marketing page.
- No commits, no pushes, no dev servers left running on 3000/3001 (use other ports for checks, and stop them).

## 6. Done means (the orchestrator tests each one)

1. `pnpm check` passes in `buyer/` and `seller/` (typecheck, lint, unit tests, counts above baseline 64 / 9).
2. With both dev servers running, `http://localhost:3000/sell` serves the seller app, and seller assets load.
3. Mock walk-through on :3000 with `?mock=1`: landing -> Sell -> New listing -> phases -> editor -> Publish -> the
   item is on the landing -> listing page -> Contact seller -> Scan -> phases -> result with a working slider.
   The orchestrator looks at a screenshot of each screen.
4. Live mode without keys: no crash, QR shown, honest "not connected yet" copy for verify.
5. Playwright e2e for the mock walk-through passes.

## 7. Blockers outside our lane (tell the user, do not fix)

- Nikhil: commit or upload the `.spz` files for the 5 scans in `gsplat/out/` (and their listing JSON if the listing
  step ran), and publish 2-3 real held-out photos per scan (today only the `heldout.jpg` sheet exists).
- Sajan: deploy `scan-upload` (the phone cannot upload without it) and `scan-session` (live phone status). Both
  return NOT_FOUND today.
- Backend (listing-link plan): nothing publishes `assets/comparisons/{id}.json` yet, so live verify cannot finish.
- Root `.env.example`: add `SELLER_ORIGIN=http://localhost:3001` (owner: Nikhil).
