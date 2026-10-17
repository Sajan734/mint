import { describe, expect, it } from "vitest";
import { decay, loadOrder, wrapIndex } from "@/components/spin-math";

describe("spin-math", () => {
  it("wraps indices both ways", () => {
    expect(wrapIndex(0, 12)).toBe(0);
    expect(wrapIndex(12, 12)).toBe(0);
    expect(wrapIndex(-1, 12)).toBe(11);
    expect(wrapIndex(25, 12)).toBe(1);
    expect(wrapIndex(5, 1)).toBe(0);
  });
  it("decays velocity and stops under the threshold", () => {
    expect(decay(1)).toBeCloseTo(0.92);
    expect(decay(0.002)).toBe(0);
    expect(decay(-0.5)).toBeCloseTo(-0.46);
  });
  it("orders load by circular distance from current", () => {
    expect(loadOrder(0, 6)).toEqual([0, 1, 5, 2, 4, 3]);
    expect(loadOrder(5, 6)).toEqual([5, 0, 4, 1, 3, 2]);
  });
});
