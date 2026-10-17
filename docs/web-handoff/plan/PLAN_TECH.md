# PLAN_TECH: technical feasibility, two-app build

Verdict: the orchestrator's leaning holds. One origin through multi-zones works in dev and prod. No repo file was edited.

What I ran. Scratch folder: `C:\Users\abhin\AppData\Local\Temp\claude\C--Users-abhin-Downloads-mint\78ab5415-80e1-4cca-b041-06a1605c7532\scratchpad\tech-probe\`.
- `zones/buyer` and `zones/seller`: copies of the real apps with edited config. Dev on 3100 and 3101, then `next build` and `next start` on 3110 and 3111.
- Chrome (devtools MCP) for HMR, links, localStorage and WebGL. `spark/` and `vt/` hold the pinned install and the vitest run.

## 1. Multi-zones

Docs, under `buyer/node_modules/next/dist/docs/01-app/`: `02-guides/multi-zones.md` (setup :38, routing :72, linking :114), `basePath.md:20,44`, `rewrites.md:397`.

**buyer/next.config.ts.** After `loadRootEnv();` (line 18) add:
```ts
const SELLER_ORIGIN = (process.env.SELLER_ORIGIN || "http://localhost:3001").replace(/\/$/, "");
// inside nextConfig (line 20), before turbopack:
async rewrites() {
  return [{ source: "/sell/:path*", destination: `${SELLER_ORIGIN}/sell/:path*` }];
},
```
- One rule is enough. `/sell/:path*` also matches `/sell` (tested: 200).
- Use `||`, not `??`. Root `.env` can hold an empty `SELLER_ORIGIN=`, and the loader keeps empty strings (line 14).
- Buyer's `/seller/[id]` route is not captured (tested: 200 from buyer).

**seller/next.config.ts.** Add `basePath: "/sell",` inside `nextConfig` (line 21). No `assetPrefix`. basePath already moves assets to `/sell/_next/...` (seen in the HTML, all 200 through the proxy).

Both files keep the root-`.env` loader, and seller keeps its `env` passthrough (line 22). My edits only add keys. `SELLER_ORIGIN` is server-side, so it needs no passthrough. Add `SELLER_ORIGIN=http://localhost:3001` to root `.env.example` (outside our write scope: tell its owner).

**What breaks in seller with basePath.** All run:
| Thing | Result |
|---|---|
| `next/link` hrefs | Auto-prefixed (`/sell/scan/new`). OK. |
| `router.push` (`ScanSession.tsx:65`) | Auto-prefixed, soft navigation. `usePathname()` drops `/sell`. OK. |
| Header logo `<Link href="/">` (`SiteHeader.tsx:7`) | Goes to `/sell`, not the shared landing. Change to `<a href="/">`. |
| `Response.redirect(new URL(..., req.url))` (`app/scan/new/route.ts:6`) | **Broken.** The browser landed on `http://localhost:3101/scan/<id>`. Inside seller, `req.url` has the upstream origin and no `/sell`. `redirect()` from `next/navigation` in a route handler also omits `/sell`. |
| `fetch("/x")` to own routes | No prefix: `/probe/h` gave 404, `/sell/probe/h` gave 200. Seller has none today (only absolute Supabase URLs, `lib/supabase.ts:17`). |
| `public/` files, `<img src="/x">` | File served only at `/sell/x`. A plain `<img src="/x">` gets no prefix. Seller has no `public/` and uses remote images (`Spin.tsx:30`). Safe. |
| Typecheck | `next typegen` and `tsc` pass. |

Fix for the redirect (tested in dev and prod: 303 to `http://localhost:3100/sell/scan/<id>`):
```ts
export function GET() {
  return new Response(null, { status: 303, headers: { Location: `/sell/scan/${crypto.randomUUID()}` } });
}
```
A relative `Location` keeps the public origin. Another option: drop the route and call `router.push(`/scan/${crypto.randomUUID()}`)` from the button.

**Dev through the rewrite works.** Opening `localhost:3100/sell` logged `[HMR] connected`. I edited a seller page. The `<h1>` changed with no reload (a `window` marker survived). Turbopack runs in both apps. If the seller is down, buyer `/sell` returns 500. Run both servers.

**Cross-zone links must be `<a>`.** Docs `multi-zones.md:114` say so. Proof: a buyer `<Link href="/sell">` click fired `/sell?_rsc=` (200) and then did nothing for 10 s. A plain `<a>` made a hard navigation. Use `<a>` for `/` and `/sell`. Use `<Link>` only inside one zone. From seller code, leave the zone with `<a href="/">` or `location.assign("/")`.

**Production.** The rewrite destination is baked at `next build`. I started `next start` with `SELLER_ORIGIN=http://localhost:9999` and it still proxied to the build-time `3111`. When you build buyer, set `SELLER_ORIGIN` first. Seller alone at `:3001/sell` works but is another origin (see 2). Always demo through the buyer origin.

## 2. Shared state

Confirmed. Same origin shares localStorage. I wrote on buyer `/probe`, read it on `/sell`, and got `null` on `:3101`. The `storage` event reached a second tab. It did not fire in the writing tab. So the store needs an in-tab listener set plus a `storage` listener. A zone change is a full page load, so each page reads on mount.

Do not reuse `mint.v1`. `buyer/lib/store.ts` owns it (`KEY` line 6). `parseState` (lines 18-29) keeps only `saved` and `orders`, so a buyer write erases a `published` field. Use a new key. Put one copy of the module in each app (separate packages, no workspace):
```ts
// lib/published.ts, identical in buyer/ and seller/
export const PUBLISHED_KEY = "mint.published.v1";
export type Published = { id: string; published_at: string; source: "mock" | "live"; item: MarketListing };
export function readPublished(s?: Pick<Storage, "getItem">): Published[];  // [] on missing, corrupt or wrong shape
export function publish(p: Published): void;                               // upsert by id, notify
export function unpublish(id: string): void;
export function subscribePublished(cb: () => void): () => void;            // listener set + window "storage" (key === PUBLISHED_KEY || null)
export function usePublished(): readonly Published[];                      // useSyncExternalStore, snapshot cached by raw string (store.ts:53-61), server snapshot = frozen []
```
Store photo URLs, never data URLs (5 MB quota). Wrap reads and writes in try/catch like `store.ts:34-36`.

## 3. 3D splat viewer

Install `three@0.180.0` and `@sparkjsdev/spark@2.1.0`, plus dev `@types/three@0.180.0` (needed, `tsc` passes). npm latest is Spark 2.3.1. Stay on 2.1.0 to match `gsplat/viewer.html:11-15`.

Spark 2.1.0 types (`node_modules/@sparkjsdev/spark/dist/types/`):
- `SplatMesh.d.ts`: options `{url, fileType, onProgress, ...}` lines 11-51. `initialized` :98, `isInitialized` :99, `dispose()` :150, `getBoundingBox()` :151.
- `SparkRenderer.d.ts`: options `{renderer, ...}` :5, class :300, `dispose()` :511, `sorting` flag.
- `defines.d.ts:20`: `fileType` is the enum `SplatFileType.SPZ`. The string `"spz"` fails `tsc`.
- The module is 5.4 MB with inline wasm and blob workers. Turbopack needs no config (dev and prod verified).
- Node import of Spark does not throw, so lazy import is mainly for size. In the prod build Spark is its own chunk: 5.07 MB raw, 1.78 MB gzip. Three is 75 KB gzip. Neither is in the page's initial scripts.

**Built and tested** in `zones/buyer`: `lib/splat-scene.ts` (imperative scene), `components/SplatViewer.tsx` (thin wrapper), `lib/viewer-slots.ts`. Copy them into the apps.
```ts
type CameraPose = { azimuth: number; polar: number; distance: number };  // distance in framing radii
type SplatViewerProps = {
  src: string; alt: string; poster?: string;
  autoRotate?: boolean;      // default true. Pass false under prefers-reduced-motion.
  interactive?: boolean;     // orbit and zoom. Default false (cards).
  maxPixelRatio?: number;    // default 2
  sharedPose?: { current: CameraPose };  // same ref in two viewers = synced cameras
  onLoad?(): void; onError?(e: Error): void; className?: string;
};
```
- The wrapper calls `import("@/lib/splat-scene")` inside `useEffect`. SSR renders only the div and poster (200). The effect creates the canvas, so StrictMode's double mount gets a fresh context.
- The canvas is transparent and starts at opacity 0. The poster `<img>` fades out on the first drawn frame.
- Framing: `getBoundingBox()` gives centre and radius (`size.length()/2`). Camera distance is `radius / sin(fov/2) * 0.9`. The butterfly rendered centred and upright with no flip. The pipeline's own `.spz` orientation is not verified.
- Drawing pauses off screen (IntersectionObserver) and in a hidden tab. `webglcontextlost` calls `onError`.
- **Disposal gotcha (measured).** `spark.dispose()` with work in flight rejects pending worker calls (`spark.module.js:2585-2591`). These are unhandled rejections, and Next's dev overlay shows "N Issues". A late `preventDefault` guard does not hide them, because Next's listener runs first. Fix in `dispose()`: stop the loop, wait until `!spark.sorting && mesh.isInitialized` (cap 8 s), then `mesh.dispose()`, `spark.dispose()`, `renderer.dispose()`, `renderer.forceContextLoss()`. Result: 16 mount/unmount cycles, half during load. 16 contexts created, 16 lost, 0 errors, 0 canvases left.
- **Context limit (measured).** I requested 40 contexts in Chrome. 16 stayed alive and 24 were lost. Safari is lower (not verified). A grid never mounts 40 viewers. `viewer-slots.ts` allows 2 at once and evicts the oldest. A card mounts a viewer after a 150 ms hover dwell. Detail page: 1 viewer. Compare: 1 or 2.
- **Card hover wiring.** `ListingCard.tsx` is a server component (lines 12-29). Its title link uses `after:absolute after:inset-0` (lines 51-53). That invisible overlay covers the image, so hover handlers on the media never fire. Put `onPointerEnter` and `onPointerLeave` on the `<article>` in a new client wrapper. Touch devices have no hover. Keep the frame spinner there.

## 4. Before/after

| Option | Risk | Effort | Blocker |
|---|---|---|---|
| (a) Image wipe | Low | 0.5 day | None |
| (b) Two synced viewers | Medium | 1 day | Needs a buyer splat |
| (c) True splat wipe | High | 1.5 days | Needs an aligned after-splat |

- (a) Two stacked `<img>`. The top one has `clip-path: inset(0 0 0 N%)`, driven by a native `<input type="range" aria-label>`. Arrow keys, Home, End and touch come free. I ran it on a real pair (`multiagent/runs/fc4b95cb.../a_00.png` and `b_00.png`, both 1024x577). The three runs I looked at have equal-size pairs per index. In a "different" run the two views really differ. The wipe shows what the agent saw.
- (b) Tested with `sharedPose`. A synthetic drag on one canvas moved both cameras (azimuth -2.01 rad on both) and the pixels matched.
- (c) Tested with two canvases and `clip-path`. A 50% wipe split the butterfly cleanly on a shared pose. The UI is easy. The data is not. The agent response has no splat (`multiagent/buyer_agent/models.py:35-39,78-79`: splats are server paths in the request, with no URLs, and the response returns images only). An after-splat in the listing's world frame is CLAUDE.md stretch N4. Pointer hit-testing under `clip-path` on touch is untested.

**Recommend (a) now.** Option (b) waits for the pipeline to publish a buyer splat. Skip (c).

## 5. Vitest and jsdom

jsdom has no WebGL. All of three and Spark sits behind `@/lib/splat-scene`, and tests `vi.mock` that one module. Done in `vt/tests/SplatViewer.test.tsx`: 7 tests pass (3.2 s). They cover:
- The poster stays until `onReady`, then `onLoad` fires once.
- `onError` reaches the parent.
- Unmount calls `dispose` once.
- Unmount before the mount finishes still disposes (race).
- Rebuild only on a `src` change, not a callback change.
- Late events after teardown are ignored.
- The slot limiter keeps 2 and evicts the oldest.

Also cover:
- `published.ts`: corrupt storage, upsert, the `storage` event via `dispatchEvent(new StorageEvent(...))`, a stable snapshot with `renderHook`.
- Card hover mounts the stub viewer, leave unmounts it, an error renders `SpinViewer`.
- Wipe: `ArrowRight` and `fireEvent.change` update the clip style. The accessible name exists.
- Mock pipeline phases with fake timers.

Env note: vitest failed in my deep scratch path (Windows 260-character limit). The repo runs fine. I used a hoisted install in `vt/`.

## 6. Performance and fallback

Measured here (Chrome, fast link). Mount to first drawn frame:
- Warm HTTP cache: 280-365 ms for a 4.0 MB splat (6 runs), 223 ms for 2.5 MB.
- Cold: 545 ms for 4.4 MB, 419 ms for 2.5 MB.
- After a `fetch(url)` to warm the cache: 366 ms for 5.4 MB. This is near the warm floor. Cache reuse is indirect evidence.
- The first hover also pays the engine JS: about 1.9 MB gzip.
- One Supabase round trip took 0.39 s, with CORS `*`. On a slow link a 4 MB splat takes seconds, so the poster carries the wait.

Plan:
1. When the grid mounts, call `requestIdleCallback(() => import("@/lib/splat-scene"))` to warm the JS.
2. Hover dwell of 150 ms, then mount. The poster is the same held-out photo, so there is no flash.
3. Wire `onProgress` (`SplatMesh.d.ts:22`) to a thin progress ring. Not built yet.
4. Fallback: if `onError` fires or `splat_url` is null, show the existing frame viewer. `SpinViewer` already has a slot (`buyer/components/SpinViewer.tsx:90`: `if (viewerUrl && splat) return <div style={box}>{splat}</div>`). The parent keeps `failed` state and passes `splat={failed ? undefined : <SplatViewer .../>}`. Seller `Spin.tsx` stays as is.
5. Label placeholder splats (`sparkjs.dev/assets/splats/*.spz`) "sample".

## Not verified
- Safari and iPhone WebGL limits and Spark speed.
- Real pipeline `.spz` files: orientation, size, Supabase `cache-control`.
- Server Actions through zones (none exist). Docs `multi-zones.md:134` say to set `allowedOrigins`.
- Real touch drags (I used synthetic pointer events).
- `redirect()` in server-component pages under basePath. Only route handlers were tested.
- The port 3000 listener (pid 30960, not mine) vanished during my run. I killed only my own pids.
