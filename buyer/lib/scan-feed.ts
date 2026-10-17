// Twin: seller/lib/scan-feed.ts (keep identical)
// The ONE live/mock seam for a phone scan (PLAN_UX section 3). reduceScan is pure and holds all phase logic;
// watchScan feeds it from whatever signals exist:
//  - the phone's status from the keyless scan-session function (scanner/supabase/functions/scan-session/index.ts),
//  - Realtime `stage` and `error` events on batch:{id} (only when the public anon key is set),
//  - the published files: assets/splats/{id}.json, and assets/listings/{id}.json (listing) or
//    assets/comparisons/{id}.json (verify; nothing publishes it yet).
// None of them is required. A later signal ticks every earlier step. Demo mode replays a recorded result instead.
import type { CompareResponse } from "./compare-types";
import type { ListingDoc } from "./listing-doc";
import { MOCK_CHECK_STAGES, MOCK_LISTING_STAGES, subStepLabel, type ScanKind } from "./progress";
import type { MarketListing } from "./types";

export type Phase = "waiting" | "connected" | "uploading" | "processing" | "ready" | "rejected" | "failed" | "cancelled";

export interface ScanState {
  phase: Phase;
  passes: number;
  uploadPct: number | null;
  subStep: string | null;
  listing: ListingDoc | null;
  compare: CompareResponse | null;
  message: string | null;
  hint: string | null;
}

/** ScanState plus what the reducer needs to remember. */
export interface FeedState extends ScanState {
  kind: ScanKind;
  live: boolean;
  spinUrls: string[] | null; // from the splat manifest, for the processing view
  changedAt: number; // ms, last visible change (for the hints)
}

export type SessionStatus = "waiting" | "scanning" | "uploading" | "uploaded" | "cancelled";

/** Every event carries `at` (ms since epoch; mockTimeline uses ms since its start). */
export type ScanEvent =
  | { type: "session"; at: number; status: SessionStatus; passes?: number; progress?: number }
  | { type: "stage"; at: number; stage: string; status: string }
  | { type: "error"; at: number; message: string | null }
  | { type: "manifest"; at: number; spinUrls: string[] }
  | { type: "listing"; at: number; doc: ListingDoc }
  | { type: "compare"; at: number; compare: CompareResponse }
  | { type: "tick"; at: number };

export const WAITING_HINT = "Still waiting for your phone. Open the Mint app and scan the code.";
export const SLOW_HINT = "This is taking longer than usual.";
export const NOT_CONNECTED = "The comparison service is not connected yet. Try demo mode (?mock=1).";

const WAITING_HINT_MS = 10 * 60_000;
const SLOW_HINT_MS = 5 * 60_000;

// cancelled ranks lowest, so a new scan with the same code resumes from it.
const RANK: Record<Phase, number> = { cancelled: -1, waiting: 0, connected: 1, uploading: 2, processing: 3, ready: 4, rejected: 4, failed: 4 };
export const isFinal = (p: Phase) => RANK[p] === 4;

export const initialScan = (kind: ScanKind, live: boolean, at: number): FeedState => ({
  phase: "waiting",
  passes: 0,
  uploadPct: null,
  subStep: null,
  listing: null,
  compare: null,
  message: null,
  hint: null,
  kind,
  live,
  spinUrls: null,
  changedAt: at,
});

/** Forward to `phase` with the patch. A stale signal for an earlier phase changes nothing. */
function advance(s: FeedState, phase: Phase, patch: Partial<FeedState> = {}): FeedState {
  return RANK[phase] < RANK[s.phase] ? s : { ...s, ...patch, phase };
}

function apply(s: FeedState, e: ScanEvent): FeedState {
  switch (e.type) {
    case "tick":
      return s;
    case "session": {
      const passes = e.passes ?? s.passes;
      if (e.status === "scanning") return advance(s, "connected", { passes });
      if (e.status === "uploading") {
        const p = typeof e.progress === "number" ? Math.min(1, Math.max(0, e.progress)) : 0;
        return advance(s, "uploading", { passes, uploadPct: Math.round(p * 100) });
      }
      if (e.status === "uploaded") return advance(s, "processing", { passes, uploadPct: 100 });
      if (e.status === "cancelled") return RANK[s.phase] < RANK.processing ? { ...s, phase: "cancelled" } : s;
      return s; // "waiting": the phone has not picked it up yet
    }
    case "stage":
      return advance(s, "processing", { subStep: subStepLabel(e.stage, s.kind) ?? s.subStep });
    case "manifest":
      return advance(s, "processing", { spinUrls: e.spinUrls });
    case "error":
      return { ...s, phase: "failed", message: e.message };
    case "listing": {
      const d = e.doc;
      if (d.status === "listed") return { ...s, phase: "ready", listing: d };
      if (d.status === "rejected") return { ...s, phase: "rejected", listing: d, message: d.rejection?.match_check.reason ?? null };
      return { ...s, phase: "failed", listing: d, message: d.error ?? null };
    }
    case "compare":
      return { ...s, phase: "ready", compare: e.compare };
  }
}

function hintFor(s: FeedState, at: number): string | null {
  const idle = at - s.changedAt;
  if (s.phase === "waiting") return idle >= WAITING_HINT_MS ? WAITING_HINT : null;
  if (s.phase === "connected" || s.phase === "uploading" || s.phase === "processing") return idle >= SLOW_HINT_MS ? SLOW_HINT : null;
  return null;
}

/** Pure: the next state. Returns the same object when nothing changed. Endings are final. */
export function reduceScan(prev: FeedState, e: ScanEvent): FeedState {
  if (isFinal(prev.phase)) return prev;
  let s = apply(prev, e);
  // A live check has no comparison service yet: say so instead of spinning forever (PLAN_UX section 3).
  if (s.kind === "verify" && s.live && s.phase === "processing" && s.message !== NOT_CONNECTED) {
    s = { ...s, subStep: s.subStep ?? subStepLabel("7_listing", "verify"), message: NOT_CONNECTED };
  }
  const changed = s.phase !== prev.phase || s.passes !== prev.passes || s.uploadPct !== prev.uploadPct || s.subStep !== prev.subStep;
  if (changed) return { ...s, changedAt: e.at, hint: null };
  const hint = hintFor(s, e.at);
  return hint === s.hint ? s : { ...s, hint };
}

// ---- demo mode ----------------------------------------------------------------------------------------------

export interface MockOptions {
  kind: ScanKind;
  scanId: string;
  /** The recorded result: a MarketListing (listing) or a CompareResponse (verify). */
  mockResult?: MarketListing | CompareResponse;
  /** ?outcome=rejected|failed: end that way instead. UI copy only, no invented reason. */
  outcome?: "rejected" | "failed";
}

const MOCK_STEP_MS = 900;
// Where live scans appear until sellers are real (gsplat/mintsplat/market.py LIVE).
const LIVE_WRAPPER = { seller_id: "sel_raj", garage_sale_id: "gs_agincourt_tech", location: { neighbourhood: "Agincourt", city: "Toronto" } };

const isMarket = (r: MockOptions["mockResult"]): r is MarketListing => !!r && "listing" in r && "frames" in r;
const isCompare = (r: MockOptions["mockResult"]): r is CompareResponse => !!r && "comparison_id" in r;

/** The recorded listing as the live pipeline would publish it for this scan: only the wrapper fields change,
 *  the way gsplat/mintsplat/market.py:99-117 sets them. */
function asLiveListing(m: MarketListing, scanId: string, now: number): MarketListing {
  return {
    ...m,
    ...LIVE_WRAPPER,
    listing: { ...m.listing, item_id: scanId },
    listed_at: new Date(now).toISOString().replace(/\.\d{3}Z$/, "Z"), // market.py writes whole seconds
  };
}

/** The demo replay, `at` = ms from the start: waiting 3 s, connected (1 then 2 passes), upload 0-100 % over 3 s,
 *  the sub-steps (900 ms each, or a check's recorded timings), then the recorded result. */
export function mockTimeline(o: MockOptions, now: number): ScanEvent[] {
  const ev: ScanEvent[] = [
    { type: "session", at: 3000, status: "scanning", passes: 1 },
    { type: "session", at: 4500, status: "scanning", passes: 2 },
  ];
  for (let i = 0; i <= 10; i++) ev.push({ type: "session", at: 5500 + i * 300, status: "uploading", passes: 2, progress: i / 10 });
  let t = 8800;
  ev.push({ type: "session", at: t, status: "uploaded", passes: 2 });

  const r = o.mockResult;
  if (o.kind === "verify") {
    for (const stage of MOCK_CHECK_STAGES) {
      ev.push({ type: "stage", at: t, stage, status: "started" });
      t += (isCompare(r) ? r.timings_ms[stage] : undefined) ?? MOCK_STEP_MS;
    }
  } else {
    for (const stage of MOCK_LISTING_STAGES) {
      // The splat manifest is published before the listing step starts (gsplat/app.py run_scan).
      if (stage === "7_listing" && isMarket(r)) ev.push({ type: "manifest", at: t, spinUrls: r.frames });
      ev.push({ type: "stage", at: t, stage, status: "started" });
      t += MOCK_STEP_MS;
    }
  }

  if (o.outcome === "rejected") ev.push({ type: "listing", at: t, doc: { v: 3, scan_id: o.scanId, status: "rejected" } });
  else if (o.kind === "listing" && isMarket(r) && o.outcome !== "failed") {
    ev.push({ type: "listing", at: t, doc: { v: 3, scan_id: o.scanId, status: "listed", market_listing: asLiveListing(r, o.scanId, now) } });
  } else if (o.kind === "verify" && isCompare(r) && o.outcome !== "failed") ev.push({ type: "compare", at: t, compare: r });
  else ev.push({ type: "error", at: t, message: null }); // ?outcome=failed, or no recorded result to show
  return ev;
}

// ---- live signals -------------------------------------------------------------------------------------------

const SUPABASE_URL = (process.env.NEXT_PUBLIC_SUPABASE_URL || "https://jpanyhsifoxxiizkgjno.supabase.co").replace(/\/$/, "");
const ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
const SESSION_URL = `${SUPABASE_URL}/functions/v1/scan-session`;
const assetUrl = (path: string) => `${SUPABASE_URL}/storage/v1/object/public/assets/${path}?t=${Date.now()}`;

const SESSION_MS = 1500;
const SESSION_MAX_MS = 15_000; // back-off cap while the function is missing (it is not deployed today)
const ASSET_MS = 2000;
const STATUSES: SessionStatus[] = ["waiting", "scanning", "uploading", "uploaded", "cancelled"];

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const num = (v: unknown) => (typeof v === "number" ? v : undefined);

async function getJson(url: string, signal: AbortSignal, init?: RequestInit): Promise<{ status: number; body: unknown } | null> {
  try {
    const res = await fetch(url, { cache: "no-store", signal, ...init });
    return { status: res.status, body: await res.json().catch(() => null) };
  } catch {
    return null; // offline, CORS, aborted: no signal
  }
}

/** The published result for this scan as an event, or null while it is missing or malformed. */
function resultEvent(kind: ScanKind, body: unknown, at: number): ScanEvent | null {
  if (!isObj(body)) return null;
  if (kind === "listing") {
    return body.status === "listed" || body.status === "rejected" || body.status === "failed"
      ? { type: "listing", at, doc: body as unknown as ListingDoc }
      : null;
  }
  return (body.status === "done" || body.status === "failed") && "verdict" in body
    ? { type: "compare", at, compare: body as unknown as CompareResponse }
    : null;
}

export interface WatchScanOptions extends MockOptions {
  listingId?: string;
  mock: boolean;
  /** Demo mode: jump straight to the end ("Skip to result"). */
  skip?: boolean;
}

/** Calls onState with the current state now and on every change. Returns the unsubscribe function, which stops
 *  every timer, request and channel. Everything also stops by itself once the scan ends. */
export function watchScan(o: WatchScanOptions, onState: (s: FeedState) => void): () => void {
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const abort = new AbortController();
  const cleanups: (() => void)[] = [];
  let stopped = false;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    timers.forEach(clearTimeout);
    abort.abort();
    cleanups.forEach((f) => f());
  };
  const later = (ms: number, fn: () => void) => {
    if (stopped) return;
    const t = setTimeout(() => {
      timers.delete(t);
      fn();
    }, ms);
    timers.add(t);
  };

  let s = initialScan(o.kind, !o.mock, Date.now());
  const emit = (e: ScanEvent) => {
    if (stopped) return;
    const next = reduceScan(s, e);
    if (next === s) return;
    s = next;
    onState(s);
    if (isFinal(s.phase)) stop();
  };
  onState(s);

  if (o.mock) {
    const t0 = Date.now();
    for (const e of mockTimeline(o, t0)) {
      if (o.skip) emit({ ...e, at: t0 });
      else later(e.at, () => emit({ ...e, at: t0 + e.at }));
    }
    return stop;
  }

  // The phone's status. 404 "no such scan" = the function is up, the phone has not reported yet. Any other
  // failure (today: NOT_FOUND, the function is not deployed) = no signal: back off, never block.
  let sessionDelay = SESSION_MS;
  const pollSession = async () => {
    const r = await getJson(SESSION_URL, abort.signal, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "status", scan_id: o.scanId }),
    });
    if (stopped) return;
    const b = r?.body;
    if (r?.status === 200 && isObj(b) && STATUSES.includes(b.status as SessionStatus)) {
      emit({ type: "session", at: Date.now(), status: b.status as SessionStatus, passes: num(b.passes), progress: num(b.progress) });
    }
    const alive = r?.status === 200 || (r?.status === 404 && isObj(b) && b.error === "no such scan");
    sessionDelay = alive ? SESSION_MS : Math.min(sessionDelay * 2, SESSION_MAX_MS);
    if (RANK[s.phase] < RANK.processing) later(sessionDelay, pollSession); // after the upload it has nothing to add
  };

  // The published files are the source of truth: the 3D scan's manifest, then the listing or comparison.
  let haveManifest = false;
  const resultPath = o.kind === "listing" ? `listings/${o.scanId}.json` : `comparisons/${o.scanId}.json`;
  const pollAssets = async () => {
    emit({ type: "tick", at: Date.now() });
    const [m, d] = await Promise.all([
      haveManifest ? null : getJson(assetUrl(`splats/${o.scanId}.json`), abort.signal),
      getJson(assetUrl(resultPath), abort.signal),
    ]);
    if (stopped) return;
    if (m?.status === 200 && isObj(m.body) && typeof m.body.splat_url === "string") {
      haveManifest = true;
      const spin = Array.isArray(m.body.spin_urls) ? m.body.spin_urls.filter((u): u is string => typeof u === "string") : [];
      emit({ type: "manifest", at: Date.now(), spinUrls: spin });
    }
    const e = d?.status === 200 ? resultEvent(o.kind, d.body, Date.now()) : null;
    if (e) emit(e);
    later(ASSET_MS, pollAssets);
  };

  void pollSession();
  void pollAssets();

  // Stage-by-stage progress from the splat job. Without the anon key the polling above still gets there.
  if (ANON_KEY) {
    import("@supabase/supabase-js")
      .then(({ createClient }) => {
        if (stopped) return;
        const sb = createClient(SUPABASE_URL, ANON_KEY);
        const inner = (p: unknown) => (isObj(p) && isObj(p.payload) ? p.payload : null); // v3 envelope
        const ch = sb
          .channel(`batch:${o.scanId}`)
          .on("broadcast", { event: "stage" }, ({ payload }) => {
            const p = inner(payload);
            if (p && typeof p.stage === "string") emit({ type: "stage", at: Date.now(), stage: p.stage, status: String(p.status ?? "") });
          })
          .on("broadcast", { event: "error" }, ({ payload }) => {
            const p = inner(payload);
            emit({ type: "error", at: Date.now(), message: p && typeof p.message === "string" ? p.message : null });
          })
          .subscribe();
        cleanups.push(() => void sb.removeChannel(ch));
      })
      .catch(() => {
        /* no Realtime: the polling still works */
      });
  }
  return stop;
}
