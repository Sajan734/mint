// Twin: buyer/tests/scan-feed.test.ts (keep identical)
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CompareResponse } from "../lib/compare-types";
import type { ListingDoc } from "../lib/listing-doc";
import { stepMark, subStepLabel } from "../lib/progress";
import {
  SLOW_HINT,
  WAITING_HINT,
  initialScan,
  mockTimeline,
  reduceScan,
  watchScan,
  type FeedState,
  type ScanEvent,
} from "../lib/scan-feed";
import type { MarketListing } from "../lib/types";

// Real recorded data: the pots listing the demo replays, and a real buyer-agent comparison run.
const readJson = <T>(rel: string): T => JSON.parse(readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8"));
const MARKET = readJson<MarketListing>("../../seller/mock/scan-result.json");
const COMPARE = readJson<CompareResponse>("../../buyer/mock/compare/435e1251.json");

const ID = "0f8b7c1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b";
const MIN = 60_000;
const doc = (status: ListingDoc["status"], extra: Partial<ListingDoc> = {}): ListingDoc => ({ v: 3, scan_id: ID, status, ...extra });
const run = (s: FeedState, ...events: ScanEvent[]) => events.reduce(reduceScan, s);
const listing = () => initialScan("listing", true, 0);

describe("reduceScan: phases", () => {
  it("starts waiting with nothing known", () => {
    expect(listing()).toMatchObject({ phase: "waiting", passes: 0, uploadPct: null, subStep: null, listing: null, compare: null, hint: null });
  });

  it("follows the phone: scanning -> connected (passes), uploading (progress), uploaded -> processing", () => {
    let s = run(listing(), { type: "session", at: 1, status: "scanning", passes: 1 });
    expect(s).toMatchObject({ phase: "connected", passes: 1 });
    s = run(s, { type: "session", at: 2, status: "scanning", passes: 2 });
    expect(s.passes).toBe(2);
    s = run(s, { type: "session", at: 3, status: "uploading", progress: 0.634 });
    expect(s).toMatchObject({ phase: "uploading", uploadPct: 63 });
    s = run(s, { type: "session", at: 4, status: "uploaded" });
    expect(s).toMatchObject({ phase: "processing", uploadPct: 100 });
  });

  it("ignores the phone's 'waiting' (not picked up yet)", () => {
    const s0 = listing();
    expect(reduceScan(s0, { type: "session", at: 1, status: "waiting" })).toBe(s0);
  });

  it("graceful skip: a later signal ticks every earlier phase", () => {
    expect(run(listing(), { type: "stage", at: 1, stage: "1_frames", status: "started" }).phase).toBe("processing");
    expect(run(listing(), { type: "manifest", at: 1, spinUrls: ["a.webp"] })).toMatchObject({ phase: "processing", spinUrls: ["a.webp"] });
    expect(run(listing(), { type: "session", at: 1, status: "uploading", progress: 0.1 }).phase).toBe("uploading");
    const ready = run(listing(), { type: "listing", at: 1, doc: doc("listed", { market_listing: MARKET }) });
    expect(ready.phase).toBe("ready");
    expect(ready.listing?.market_listing?.listing.title).toBe(MARKET.listing.title);
    for (const id of ["waiting", "connected", "uploading", "processing", "ready"] as const) expect(stepMark(id, ready.phase)).toBe("done");
  });

  it("never goes back when a stale signal arrives", () => {
    const s = run(listing(), { type: "stage", at: 1, stage: "4_train", status: "started" }, { type: "session", at: 2, status: "scanning", passes: 1 });
    expect(s.phase).toBe("processing");
    expect(run(s, { type: "session", at: 3, status: "uploading", progress: 0.2 }).phase).toBe("processing");
  });

  it("names the sub-step from the stage prefix and keeps it for unknown stages", () => {
    let s = run(listing(), { type: "stage", at: 1, stage: "2_masks_top", status: "started" });
    expect(s.subStep).toBe("Finding the item");
    s = run(s, { type: "stage", at: 2, stage: "something_new", status: "started" });
    expect(s.subStep).toBe("Finding the item");
    expect(subStepLabel("3b_register", "listing")).toBe("Working out the angles");
    expect(subStepLabel("7_listing", "listing")).toBe("Writing your listing");
    expect(subStepLabel("7_listing", "verify")).toBe("Comparing with the listing");
    expect(subStepLabel("6_views", "listing")).toBe("Cleaning up");
  });
});

describe("reduceScan: endings", () => {
  it("cancelled on the phone, and a later scan with the same code resumes", () => {
    let s = run(listing(), { type: "session", at: 1, status: "scanning", passes: 1 }, { type: "session", at: 2, status: "cancelled" });
    expect(s.phase).toBe("cancelled");
    expect(stepMark("connected", s.phase)).toBe("stopped");
    s = run(s, { type: "session", at: 3, status: "scanning", passes: 1 });
    expect(s.phase).toBe("connected");
  });

  it("a cancel after the upload finished is stale and ignored", () => {
    const s = run(listing(), { type: "session", at: 1, status: "uploaded" }, { type: "session", at: 2, status: "cancelled" });
    expect(s.phase).toBe("processing");
  });

  it("rejected with the listing step's reason, or none", () => {
    const withReason = run(listing(), { type: "listing", at: 1, doc: doc("rejected", { rejection: { match_check: { verdict: "mismatch", reason: "reason text" } } }) });
    expect(withReason).toMatchObject({ phase: "rejected", message: "reason text" });
    expect(stepMark("processing", withReason.phase)).toBe("stopped");
    expect(run(listing(), { type: "listing", at: 1, doc: doc("rejected") })).toMatchObject({ phase: "rejected", message: null });
  });

  it("failed from the listing document or a Realtime error event", () => {
    expect(run(listing(), { type: "listing", at: 1, doc: doc("failed", { error: "boom" }) })).toMatchObject({ phase: "failed", message: "boom" });
    const s = run(listing(), { type: "stage", at: 1, stage: "4_train", status: "started" }, { type: "error", at: 2, message: "CUDA out of memory" });
    expect(s).toMatchObject({ phase: "failed", message: "CUDA out of memory" });
  });

  it("an ending is final: later events change nothing", () => {
    const done = run(listing(), { type: "error", at: 1, message: null });
    expect(reduceScan(done, { type: "listing", at: 2, doc: doc("listed", { market_listing: MARKET }) })).toBe(done);
    expect(reduceScan(done, { type: "tick", at: 99 * MIN })).toBe(done);
  });

  it("a check ends with the comparison", () => {
    const s = run(initialScan("verify", true, 0), { type: "compare", at: 1, compare: COMPARE });
    expect(s.phase).toBe("ready");
    expect(s.compare?.comparison_id).toBe(COMPARE.comparison_id);
  });
});

describe("reduceScan: live check and hints", () => {
  it("a live check follows the pipeline like a listing: splat steps, then comparing, then the result", () => {
    let s = run(initialScan("verify", true, 0), { type: "session", at: 1, status: "uploaded" });
    expect(s).toMatchObject({ phase: "processing", message: null });
    s = run(s, { type: "stage", at: 2, stage: "7_listing", status: "started" });
    expect(s).toMatchObject({ phase: "processing", subStep: "Comparing with the listing", message: null });
    expect(run(s, { type: "compare", at: 3, compare: COMPARE }).phase).toBe("ready");
  });

  it("a demo check has no such message", () => {
    const s = run(initialScan("verify", false, 0), { type: "session", at: 1, status: "uploaded" });
    expect(s.message).toBeNull();
  });

  it("hints after 10 min waiting, or 5 min without change; a change clears it", () => {
    expect(run(listing(), { type: "tick", at: 9 * MIN }).hint).toBeNull();
    expect(run(listing(), { type: "tick", at: 10 * MIN }).hint).toBe(WAITING_HINT);
    let s = run(listing(), { type: "session", at: MIN, status: "scanning", passes: 1 }, { type: "tick", at: 5 * MIN });
    expect(s.hint).toBeNull();
    s = run(s, { type: "tick", at: 6 * MIN });
    expect(s.hint).toBe(SLOW_HINT);
    s = run(s, { type: "session", at: 7 * MIN, status: "scanning", passes: 2 });
    expect(s.hint).toBeNull();
  });
});

describe("mockTimeline", () => {
  it("replays the recorded listing with only the wrapper fields changed (gsplat/mintsplat/market.py)", () => {
    const now = Date.parse("2026-10-17T15:00:00.123Z");
    const events = mockTimeline({ kind: "listing", scanId: ID, mockResult: MARKET }, now);
    const last = events.at(-1)!;
    expect(last.type).toBe("listing");
    const m = (last as Extract<ScanEvent, { type: "listing" }>).doc.market_listing!;
    expect(m.listing.item_id).toBe(ID);
    expect(m).toMatchObject({ seller_id: "sel_raj", garage_sale_id: "gs_agincourt_tech", location: { neighbourhood: "Agincourt", city: "Toronto" }, listed_at: "2026-10-17T15:00:00Z" });
    // Everything the listing agent wrote stays as it was.
    expect(m.listing.title).toBe(MARKET.listing.title);
    expect(m.listing.price_cad).toBe(MARKET.listing.price_cad);
    expect(m.frames).toEqual(MARKET.frames);
    expect(m.splat_url).toBe(MARKET.splat_url);
    expect(events.map((e) => e.at)).toEqual([...events.map((e) => e.at)].sort((a, b) => a - b));
  });

  it("ends rejected or failed for ?outcome= without inventing a reason", () => {
    const rej = mockTimeline({ kind: "listing", scanId: ID, mockResult: MARKET, outcome: "rejected" }, 0);
    expect(run(listing(), ...rej)).toMatchObject({ phase: "rejected", message: null });
    const fail = mockTimeline({ kind: "verify", scanId: ID, mockResult: COMPARE, outcome: "failed" }, 0);
    expect(run(initialScan("verify", false, 0), ...fail)).toMatchObject({ phase: "failed", message: null });
  });

  it("a demo check takes as long as the recorded run's steps", () => {
    const events = mockTimeline({ kind: "verify", scanId: ID, mockResult: COMPARE }, 0);
    const t = COMPARE.timings_ms;
    const uploaded = events.find((e) => e.type === "session" && e.status === "uploaded")!.at;
    expect(events.at(-1)!.at - uploaded).toBe(t.judge + t.claims + t.advise);
  });
});

describe("watchScan", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  const respond = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status }));

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse("2026-10-17T15:00:00Z"));
    fetchMock = vi.fn(() => respond(404, { code: "NOT_FOUND", message: "Requested function was not found" }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("mock: waiting 3 s, passes 1 then 2, upload 0-100 %, sub-steps, then ready", async () => {
    const seen: FeedState[] = [];
    const stop = watchScan({ scanId: ID, kind: "listing", mock: true, mockResult: MARKET }, (s) => seen.push(s));
    expect(seen.at(-1)!.phase).toBe("waiting");
    await vi.advanceTimersByTimeAsync(2999);
    expect(seen.at(-1)!.phase).toBe("waiting");
    await vi.advanceTimersByTimeAsync(1);
    expect(seen.at(-1)).toMatchObject({ phase: "connected", passes: 1 });
    await vi.advanceTimersByTimeAsync(2500);
    expect(seen.at(-1)!.passes).toBe(2);
    await vi.advanceTimersByTimeAsync(3000);
    const pcts = seen.filter((s) => s.phase === "uploading").map((s) => s.uploadPct);
    expect(pcts[0]).toBe(0);
    expect(pcts.at(-1)).toBe(100);
    await vi.advanceTimersByTimeAsync(20_000);
    const subs = [...new Set(seen.map((s) => s.subStep).filter(Boolean))];
    expect(subs).toEqual(["Reading the video", "Finding the item", "Working out the angles", "Building the 3D model", "Cleaning up", "Writing your listing"]);
    expect(seen.at(-1)!.phase).toBe("ready");
    expect(seen.at(-1)!.listing?.market_listing?.listing.item_id).toBe(ID);
    expect(fetchMock).not.toHaveBeenCalled(); // demo mode never touches the network
    stop();
  });

  it("mock skip: straight to the result", () => {
    const seen: FeedState[] = [];
    watchScan({ scanId: ID, kind: "verify", listingId: "pots_i1", mock: true, mockResult: COMPARE, skip: true }, (s) => seen.push(s));
    expect(seen.at(-1)).toMatchObject({ phase: "ready", compare: COMPARE });
  });

  it("unsubscribe stops the timers and the polling", async () => {
    const onState = vi.fn();
    const stopMock = watchScan({ scanId: ID, kind: "listing", mock: true, mockResult: MARKET }, onState);
    stopMock();
    const live = watchScan({ scanId: ID, kind: "listing", mock: false }, onState);
    await vi.advanceTimersByTimeAsync(0);
    live();
    const calls = onState.mock.calls.length;
    const fetches = fetchMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(onState.mock.calls.length).toBe(calls);
    expect(fetchMock.mock.calls.length).toBe(fetches);
  });

  it("live: scan-session 404 never blocks; the published files still move it to ready, and the session poll backs off", async () => {
    let splatAt = Infinity;
    const manifest = { scan_id: ID, splat_url: "x.spz", spin_urls: ["f00.webp"], stage_timings_ms: {} };
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/functions/v1/scan-session")) return respond(404, { code: "NOT_FOUND", message: "Requested function was not found" });
      if (url.includes(`/splats/${ID}.json`) && Date.now() >= splatAt) return respond(200, manifest);
      if (url.includes(`/listings/${ID}.json`) && Date.now() >= splatAt + 4000) return respond(200, doc("listed", { market_listing: MARKET }));
      return respond(400, { error: "not found" });
    });
    const seen: FeedState[] = [];
    const stop = watchScan({ scanId: ID, kind: "listing", mock: false }, (s) => seen.push(s));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(seen.at(-1)!.phase).toBe("waiting");
    const sessionCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes("scan-session")).length;
    expect(sessionCalls).toBeLessThan(15); // 1.5 s would be 40; it backs off

    splatAt = Date.now();
    await vi.advanceTimersByTimeAsync(2000);
    expect(seen.at(-1)).toMatchObject({ phase: "processing", spinUrls: ["f00.webp"] });
    await vi.advanceTimersByTimeAsync(6000);
    expect(seen.at(-1)!.phase).toBe("ready");
    const after = fetchMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetchMock.mock.calls.length).toBe(after); // polling ends with the scan
    stop();
  });

  it("live: the phone's status moves the steps (POST status to the keyless function)", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/functions/v1/scan-session")) {
        expect(JSON.parse(String(init?.body))).toEqual({ action: "status", scan_id: ID });
        return respond(200, { v: 1, scan_id: ID, status: "uploading", passes: 2, progress: 0.5 });
      }
      return respond(400, {});
    });
    const seen: FeedState[] = [];
    const stop = watchScan({ scanId: ID, kind: "listing", mock: false }, (s) => seen.push(s));
    await vi.advanceTimersByTimeAsync(10);
    expect(seen.at(-1)).toMatchObject({ phase: "uploading", uploadPct: 50 });
    stop();
  });
});
