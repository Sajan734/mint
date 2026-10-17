import { afterEach, describe, expect, it, vi } from "vitest";
import { getListing, getListings } from "../lib/data";
import { listings } from "../lib/data/mock";
import { getLiveListings, liveIndexUrl, parseLiveIndex } from "../lib/data/live";
// Written by gsplat/mintsplat/market.py from listing/'s fixtures item01 (listed) and item02 (rejected), plus one
// scan whose listing step failed.
import liveIndex from "./fixtures/live-index.json";

const LISTED = "11111111-0000-4000-8000-000000000001";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

const serve = (body: unknown, ok = true) => {
  const fetchMock = vi.fn(async () => ({ ok, json: async () => body }));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("MINT_LIVE_LISTINGS", "1");
  return fetchMock;
};

describe("parseLiveIndex", () => {
  it("keeps only published listed scans that pass the MarketListing schema", () => {
    const live = parseLiveIndex(liveIndex);
    expect(live.map((m) => m.listing.item_id)).toEqual([LISTED]);
    expect(live[0].frames).toHaveLength(24);
    expect(live[0].category).toBe("electronics");
    expect(live[0].reference_price_cad).toBe(live[0].listing.price_cad);
  });

  it("hides a listing the seller has not published yet", () => {
    const draft = { scans: liveIndex.scans.map((d) => ({ ...d, published: false })) };
    expect(parseLiveIndex(draft)).toEqual([]);
  });

  it("skips documents that break the schema and tolerates junk", () => {
    const bad = { scans: [{ status: "listed", published: true, market_listing: { listing: { title: "x" } } }] };
    expect(parseLiveIndex(bad)).toEqual([]);
    expect(parseLiveIndex(null)).toEqual([]);
    expect(parseLiveIndex({ scans: "nope" })).toEqual([]);
  });
});

describe("getLiveListings", () => {
  it("reads the public index without caching", async () => {
    const fetchMock = serve(liveIndex);
    expect((await getLiveListings()).map((m) => m.listing.item_id)).toEqual([LISTED]);
    expect(fetchMock).toHaveBeenCalledWith(liveIndexUrl(), expect.objectContaining({ cache: "no-store" }));
  });

  it("returns nothing when the index is missing or the network fails", async () => {
    serve({}, false);
    expect(await getLiveListings()).toEqual([]);
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    expect(await getLiveListings()).toEqual([]);
  });

  it("stays off in unit tests unless asked, and when MINT_LIVE_LISTINGS=0", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect(await getLiveListings()).toEqual([]);
    vi.stubEnv("MINT_LIVE_LISTINGS", "0");
    expect(await getLiveListings()).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("data layer with live scans", () => {
  it("puts live scans first, then the mock listings", async () => {
    serve(liveIndex);
    const all = await getListings();
    expect(all).toHaveLength(listings.length + 1);
    expect(all[0].listing.item_id).toBe(LISTED); // newest listed_at sorts first
    expect((await getListing(LISTED))?.listing.title).toMatch(/Sony/);
  });
});
