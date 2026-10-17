// Covers lib/mock-mode.ts; the seller copy is byte-identical, so one test file is enough.
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  DEMO_SELLER_ID, MOCK_KEY, SAMPLE_SPLATS, isMockMode, sampleSplatFor, setMockMode, useMockMode,
} from "../lib/mock-mode";

const url = (qs: string) => window.history.replaceState({}, "", `/${qs}`);

beforeEach(() => {
  localStorage.clear();
  url("");
});

describe("mock switch", () => {
  it("is off by default", () => {
    expect(isMockMode()).toBe(false);
    expect(DEMO_SELLER_ID).toBe("sel_raj");
  });
  it("?mock=1 turns it on and remembers it after the URL changes", () => {
    url("?mock=1");
    expect(isMockMode()).toBe(true);
    expect(localStorage.getItem(MOCK_KEY)).toBe("1");
    url("");
    expect(isMockMode()).toBe(true);
  });
  it("?mock=0 turns it off again", () => {
    localStorage.setItem(MOCK_KEY, "1");
    url("?mock=0");
    expect(isMockMode()).toBe(false);
    url("");
    expect(isMockMode()).toBe(false);
  });
  it("ignores other values of the param", () => {
    localStorage.setItem(MOCK_KEY, "1");
    url("?mock=banana");
    expect(isMockMode()).toBe(true);
  });
  it("setMockMode(false) wins over a ?mock=1 still in the URL, and drops the param", () => {
    url("?mock=1&x=2");
    expect(isMockMode()).toBe(true);
    setMockMode(false);
    expect(isMockMode()).toBe(false);
    expect(window.location.search).toBe("?x=2");
  });
  it("survives blocked storage", () => {
    const real = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new Error("blocked");
    };
    try {
      expect(isMockMode()).toBe(false);
      expect(() => setMockMode(true)).not.toThrow();
    } finally {
      Storage.prototype.getItem = real;
    }
  });
});

describe("useMockMode", () => {
  it("follows setMockMode in the same tab", () => {
    const { result } = renderHook(() => useMockMode());
    expect(result.current).toBe(false);
    act(() => setMockMode(true));
    expect(result.current).toBe(true);
    act(() => setMockMode(false));
    expect(result.current).toBe(false);
  });
  it("follows the storage event from another tab", () => {
    const { result } = renderHook(() => useMockMode());
    act(() => {
      localStorage.setItem(MOCK_KEY, "1");
      window.dispatchEvent(new StorageEvent("storage", { key: MOCK_KEY }));
    });
    expect(result.current).toBe(true);
  });
  it("picks up ?mock=1 on mount", () => {
    url("?mock=1");
    const { result } = renderHook(() => useMockMode());
    expect(result.current).toBe(true);
  });
});

describe("sample splats", () => {
  it("are the five sparkjs.dev samples", () => {
    expect(SAMPLE_SPLATS).toHaveLength(5);
    for (const u of SAMPLE_SPLATS) expect(u).toMatch(/^https:\/\/sparkjs\.dev\/assets\/splats\/[a-z-]+\.spz$/);
  });
  it("sampleSplatFor is deterministic and spreads ids over the list", () => {
    expect(sampleSplatFor("pots_i1")).toBe(sampleSplatFor("pots_i1"));
    const picks = new Set(Array.from({ length: 40 }, (_, i) => sampleSplatFor(`item_${i}`)));
    expect(picks.size).toBeGreaterThan(2);
    for (const p of picks) expect(SAMPLE_SPLATS).toContain(p);
  });
  it("handles an empty id", () => {
    expect(SAMPLE_SPLATS).toContain(sampleSplatFor(""));
  });
});
