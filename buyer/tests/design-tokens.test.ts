// @vitest-environment node
// The theme's text pairs pass WCAG AA (4.5:1), read from the real CSS (light mode only).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2].toLowerCase()]));
}
const light = block(":root {");

function luminance(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

// [foreground, background] token pairs that carry text.
const PAIRS: [string, string][] = [
  ["ink", "bg"],
  ["ink-2", "bg"],
  ["ink", "surface"],
  ["ink-2", "surface"],
  ["leaf", "bg"],
  ["leaf", "wash"],
  ["bg", "ink"], // button text (paper) on the ink button
  ["amber", "amber-wash"],
  ["coral", "coral-wash"],
];

describe("design tokens", () => {
  it.each(PAIRS)("light: %s on %s is at least 4.5:1", (fg, bg) => {
    expect(contrast(light[fg], light[bg])).toBeGreaterThanOrEqual(4.5);
  });
  it("type on the light band passes", () => {
    expect(contrast(light["on-pine"], light.pine)).toBeGreaterThanOrEqual(7);
    expect(contrast(light["on-pine-2"], light.pine)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(light.leaf, light.pine)).toBeGreaterThanOrEqual(4.5);
  });
  it("is light mode only", () => {
    expect(css).not.toMatch(/prefers-color-scheme: dark|data-theme="dark"/);
  });
  it("the seller app uses the same tokens", () => {
    expect(readFileSync(new URL("../../seller/app/globals.css", import.meta.url), "utf8")).toBe(css);
  });
});
