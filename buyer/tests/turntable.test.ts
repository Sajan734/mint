import { describe, expect, it } from "vitest";
import { PALETTE_NAMES, SHAPES, renderTurntableFrame } from "@/lib/turntable";

describe("turntable", () => {
  it("is deterministic", () => {
    expect(renderTurntableFrame("mug", "sage", 3)).toBe(renderTurntableFrame("mug", "sage", 3));
  });
  it("renders every shape as valid-looking SVG with polygons", () => {
    for (const s of SHAPES) {
      const svg = renderTurntableFrame(s, "clay", 5);
      expect(svg.startsWith("<svg")).toBe(true);
      expect(svg.endsWith("</svg>")).toBe(true);
      expect(svg).not.toContain("NaN");
      expect((svg.match(/<polygon/g) ?? []).length).toBeGreaterThan(8);
    }
  });
  it("frame n differs from n + total/2 and n + 1", () => {
    for (const s of SHAPES) {
      expect(renderTurntableFrame(s, "sage", 0)).not.toBe(renderTurntableFrame(s, "sage", 12));
      expect(renderTurntableFrame(s, "sage", 0)).not.toBe(renderTurntableFrame(s, "sage", 1));
    }
  });
  it("palettes change colour", () => {
    expect(new Set(PALETTE_NAMES.map((p) => renderTurntableFrame("vase", p, 0))).size).toBe(PALETTE_NAMES.length);
  });
});
