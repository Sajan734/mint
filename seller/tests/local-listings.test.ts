// Twin: buyer/tests/local-listings.test.ts (keep identical)
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  LOCAL_KEY, getLocal, listLocal, parseListings, upsertLocal, useLocalListings, type LocalListing,
} from "../lib/local-listings";
import type { MarketListing } from "../lib/types";

const market: MarketListing = {
  listing: {
    item_id: "i1", title: "Pot", description: "d", attributes: {}, tags: [], condition_grade: "like_new",
    condition_notes: [], price_cad: 20, price_justification: [], preview_images: [], viewer_url: null,
    needs_seller_check: false, seller_check_reasons: [],
  },
  seller_id: "sel_raj", garage_sale_id: "gs_agincourt_tech", category: "home_kitchen",
  location: { neighbourhood: "Agincourt", city: "Toronto" }, reference_price_cad: 25, frames: ["/f.jpg"],
  splat_url: null, usable_view_count: 8, listed_at: "2026-10-17T00:00:00Z", status: "available",
};
const entry = (id: string, over: Partial<LocalListing> = {}): LocalListing => ({
  id, state: "draft", source: "mock", suggested_price_cad: 25, market,
  created_at: "2026-10-17T00:00:00Z", updated_at: "2026-10-17T00:00:00Z", ...over,
});

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("parseListings", () => {
  it("returns [] for missing, corrupt or wrong-shape storage", () => {
    expect(parseListings(null)).toEqual([]);
    expect(parseListings("{not json")).toEqual([]);
    expect(parseListings('{"a":1}')).toEqual([]);
    expect(parseListings('"text"')).toEqual([]);
  });
  it("drops entries that are not listings and keeps the good ones", () => {
    const good = entry("a");
    const raw = JSON.stringify([good, { id: 1 }, null, { ...good, id: "b", state: "weird" }, "x"]);
    expect(parseListings(raw)).toEqual([good]);
  });
});

describe("store", () => {
  it("is empty on a fresh or corrupt browser", () => {
    expect(listLocal()).toEqual([]);
    localStorage.setItem(LOCAL_KEY, "{oops");
    expect(listLocal()).toEqual([]);
    expect(getLocal("a")).toBeNull();
  });
  it("uses its own key, never mint.v1", () => {
    expect(LOCAL_KEY).toBe("mint.listings.v1");
  });
  it("upsert adds, then replaces by id in place", () => {
    upsertLocal(entry("a"));
    upsertLocal(entry("b"));
    upsertLocal(entry("a", { state: "published", published_at: "2026-10-17T01:00:00Z" }));
    expect(listLocal().map((l) => l.id)).toEqual(["a", "b"]);
    expect(getLocal("a")?.state).toBe("published");
    expect(JSON.parse(localStorage.getItem(LOCAL_KEY) ?? "[]")).toHaveLength(2);
  });
  it("does not throw when storage refuses the write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    expect(() => upsertLocal(entry("a"))).not.toThrow();
  });
  it("reads as empty on the server (no window)", () => {
    vi.stubGlobal("window", undefined);
    expect(listLocal()).toEqual([]);
  });
});

describe("useLocalListings", () => {
  it("returns a stable snapshot while storage is unchanged", () => {
    upsertLocal(entry("a"));
    const { result, rerender } = renderHook(() => useLocalListings());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
    expect(first.map((l) => l.id)).toEqual(["a"]);
  });
  it("tells same-tab listeners about a write", () => {
    const { result } = renderHook(() => useLocalListings());
    expect(result.current).toEqual([]);
    act(() => upsertLocal(entry("a")));
    expect(result.current.map((l) => l.id)).toEqual(["a"]);
    act(() => upsertLocal(entry("a", { suggested_price_cad: 30 })));
    expect(result.current[0].suggested_price_cad).toBe(30);
  });
  it("follows the storage event from another tab", () => {
    const { result } = renderHook(() => useLocalListings());
    act(() => {
      localStorage.setItem(LOCAL_KEY, JSON.stringify([entry("z")]));
      window.dispatchEvent(new StorageEvent("storage", { key: LOCAL_KEY }));
    });
    expect(result.current.map((l) => l.id)).toEqual(["z"]);
  });
  it("ignores storage events for other keys", () => {
    const { result } = renderHook(() => useLocalListings());
    const before = result.current;
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: "mint.v1" }));
    });
    expect(result.current).toBe(before);
  });
  it("stops listening after unmount", () => {
    const { unmount } = renderHook(() => useLocalListings());
    unmount();
    expect(() => upsertLocal(entry("a"))).not.toThrow();
  });
});
