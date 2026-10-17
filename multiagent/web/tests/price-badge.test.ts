import { describe, expect, it } from "vitest";
import { dealRatio, priceBadge } from "../lib/price-badge";

describe("priceBadge", () => {
  it.each([
    [85, 100, "great"], // r = 0.85 inclusive
    [86, 100, "fair"],
    [110, 100, "fair"], // r = 1.10 inclusive
    [111, 100, "high"],
    [130, 100, "high"], // r = 1.30 inclusive
    [131, 100, "overpriced"],
    [50, 100, "great"],
  ])("price %i vs ref %i -> %s", (p, ref, kind) => {
    expect(priceBadge(p, ref).kind).toBe(kind);
  });

  it("no reference -> unknown", () => {
    expect(priceBadge(50, null)).toEqual({ kind: "unknown", label: "No price check", pctVsFair: null });
  });

  it("pctVsFair and labels", () => {
    expect(priceBadge(88, 100).pctVsFair).toBe(-12);
    expect(priceBadge(108, 100).pctVsFair).toBe(8);
    expect(priceBadge(80, 100).label).toBe("Great price");
    expect(priceBadge(120, 100).label).toBe("A bit high");
  });

  it("dealRatio puts unknowns last", () => {
    expect(dealRatio(10, null)).toBe(Infinity);
    expect(dealRatio(50, 100)).toBe(0.5);
  });
});
