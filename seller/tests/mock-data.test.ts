// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const readJson = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), "utf8"));
const buyer = readJson("../../buyer/mock/listings.json") as { seller_id: string; status: string; listing: { item_id: string } }[];

describe("seller mock data", () => {
  it("my-listings.json is exactly the sel_raj entries of the buyer's listings.json", () => {
    const mine = readJson("../mock/my-listings.json");
    expect(mine).toEqual(buyer.filter((m) => m.seller_id === "sel_raj"));
  });
  it("shows how items sold: 2 sold, 1 reserved, 2 available", () => {
    const counts: Record<string, number> = {};
    for (const m of readJson("../mock/my-listings.json") as { status: string }[]) counts[m.status] = (counts[m.status] ?? 0) + 1;
    expect(counts).toEqual({ available: 2, reserved: 1, sold: 2 });
  });
  it("scan-result.json is the real ThinkPad listing, with only its URLs pointed at local copies", () => {
    const real = readJson("../../gsplat/out/scan_a6816dfc/listing.json").market_listing;
    const result = readJson("../mock/scan-result.json");
    const urls = (x: unknown): unknown =>
      typeof x === "string" && /^(https:\/\/|\/demo\/)/.test(x) ? "URL" : Array.isArray(x) ? x.map(urls)
        : x && typeof x === "object" ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, urls(v)])) : x;
    expect(urls(result)).toEqual(urls(real));
    const local = [result.splat_url, ...result.frames, ...result.listing.preview_images] as string[];
    for (const u of local) {
      expect(u.startsWith("/demo/listings/a6816dfc/")).toBe(true);
      expect(existsSync(fileURLToPath(new URL(`../../buyer/public${u}`, import.meta.url).href))).toBe(true);
    }
  });
  it("real-scans.json lists the 5 real scans as scanned, with no listing text, price or condition", () => {
    const rows = readJson("../mock/real-scans.json") as Record<string, unknown>[];
    expect(rows.map((r) => r.id)).toEqual(["scan_backpack", "scan_chair", "scan_phone", "scan_merged", "scan_live_check"]);
    for (const r of rows) {
      expect(r.state).toBe("scanned");
      expect(r.splat_url).toBeNull();
      expect((r.images as string[]).every((u) => u.startsWith("/demo/scans/"))).toBe(true);
      for (const k of ["price_cad", "price", "condition_grade", "description", "title"]) expect(r).not.toHaveProperty(k);
    }
    expect((rows[4].spin_frames as string[]).length).toBe(24);
  });
});
