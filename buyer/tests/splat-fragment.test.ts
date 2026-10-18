// Twin: seller/tests/splat-fragment.test.ts (keep identical)
import { describe, expect, it } from "vitest";
import { fragmentMaxPolar, fragmentRotation } from "@/lib/splat-scene";

describe("splat URL fragments", () => {
  it("a one-pass scan's #maxpolar=90 keeps the camera on the top half", () => {
    expect(fragmentMaxPolar("https://x.supabase.co/a/splats/id.spz#maxpolar=90")).toBeCloseTo(Math.PI / 2);
  });
  it("no limit, or a nonsense one, lets the camera go all the way round", () => {
    expect(fragmentMaxPolar("https://x.supabase.co/a/splats/id.spz")).toBe(Math.PI);
    expect(fragmentMaxPolar("/s.spz#maxpolar=0")).toBe(Math.PI);
    expect(fragmentMaxPolar("/s.spz#maxpolar=abc")).toBe(Math.PI);
  });
  it("reads alongside a rotation", () => {
    const src = "/s.ply#rx=180&maxpolar=90";
    expect(fragmentMaxPolar(src)).toBeCloseTo(Math.PI / 2);
    expect(fragmentRotation(src)[0]).toBeCloseTo(Math.PI);
  });
});
