# Rules for every wave-2 agent (read after PLAN.md)

Repo C:\Users\abhin\Downloads\mint, branch ba/two-sites. Never switch branches, never commit or push.

1. Read PLAN.md (whole), then the PLAN_UX / PLAN_TECH sections your prompt names, then your app's AGENTS.md
   (Next.js 16.4.2 differs from what you know: read node_modules/next/dist/docs/ for anything Next-specific).
2. Edit ONLY the files your prompt lists. Five agents edit this checkout at the same time. If you need a change in
   a file you do not own, stop and describe it in your report.
3. T1 already wrote: lib/local-listings.ts, lib/mock-mode.ts, lib/compare-types.ts, lib/listing-doc.ts (both apps,
   real code), both SiteHeaders, and typed STUBS of lib/scan-feed.ts, components/ScanFlow.tsx,
   components/SplatViewer.tsx, components/MediaPanel.tsx. Import from them. Do not edit them unless you own them.
4. Media API (owned by T3, used by T4/T5): components/MediaPanel.tsx exports `MediaProvider`
   ({title, splatUrl, frames, photos, sample?, children}), `MediaViewer` (the big view: 3D or the selected photo),
   `MediaTiles` (the row: a "3D" tile, then up to 3 photo tiles; clicking one selects it), and default `MediaPanel`
   (viewer + tiles stacked). Selection state lives in the provider. T3 writes these names FIRST.
5. Scan API (owned by T2): `watchScan({scanId, kind, listingId?, mock, mockResult?}, onState)`, where `mockResult` is
   the ListingDoc (listing) or CompareResponse (verify) to replay in mock mode. `<ScanFlow kind scanId listingId?
   deepLink qrSvg mockResult? onDone? />`. Pages import their own mock JSON and pass it in.
6. Data: demo files from T7 live in buyer/public/demo/scans/** (real gsplat scans), buyer/public/local/** (PASLCD
   frames + compare view images, gitignored), buyer/mock/compare/{435e1251,fc4b95cb,cce6fb01}.json (real agent
   output), seller/mock/{scan-result,my-listings,real-scans}.json. Real data only. Never invent agent output.
7. Checks (targeted, because others are mid-edit): `pnpm exec vitest run <your test files>`,
   `pnpm exec eslint <your files>`, `pnpm exec tsc --noEmit -p .` (report errors in files you do not own; do not fix).
   Tests first for pure logic.
8. LOOK at your screens. A shared preview runs at http://localhost:3300 (buyer, the one origin; /sell is the seller
   zone). Never start or stop servers on 3000, 3001, 3300 or 3301. Screenshot with
   `pnpm exec playwright screenshot --viewport-size=1280,900 --wait-for-timeout=2500 "<url>" <file.png>` and also
   390,844 for phone, into C:\Users\abhin\AppData\Local\Temp\claude\C--Users-abhin-Downloads-mint\78ab5415-80e1-4cca-b041-06a1605c7532\scratchpad\shots\<your task>\ ,
   then open the PNG with your Read tool and fix what looks wrong. Add `?mock=1` to turn demo mode on.
9. Design: keep the tokens in app/globals.css (the same mint brand as the iOS app, scanner/ios/Mint/Brand.swift).
   Marketplace feel (Amazon / Facebook Marketplace): dense, calm, product-first. No AI tropes: no gradient washes,
   no emoji, no left-border accent cards, no glassmorphism. Real <button>/<a>, labels, visible focus, 44 px targets,
   text contrast 4.5:1, prefers-reduced-motion. Short plain copy (PLAN_UX §7).
10. Report: files changed, test results (pasted), screenshots you looked at and what you fixed, anything unfinished,
    and any change needed in a file you do not own.
