import { readFileSync } from "node:fs";
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
  it("scan-result.json is exactly the pots_i1 entry", () => {
    expect(readJson("../mock/scan-result.json")).toEqual(buyer.find((m) => m.listing.item_id === "pots_i1"));
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
