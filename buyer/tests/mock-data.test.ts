import { existsSync, readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { garageSales, listings, orders, sellers, verifySample, frameFallbacks } from "../lib/data/mock";
import { priceBadge } from "../lib/price-badge";
import listingsRaw from "../mock/listings.json";
import sellersJson from "../mock/sellers.json";

const file = (rel: string) => new URL(rel, import.meta.url);
const readJson = (rel: string) => JSON.parse(readFileSync(file(rel), "utf8"));
const RUNS = file("../../multiagent/runs/"); // gitignored: only present on a machine that ran the agents
const RUN_PREFIXES = ["435e1251", "fc4b95cb", "cce6fb01"];
const runDir = (prefix: string) => (existsSync(RUNS) ? readdirSync(RUNS).find((d) => d.startsWith(prefix)) : undefined);

const count = <T,>(xs: T[], f: (x: T) => string) => xs.reduce<Record<string, number>>((a, x) => ((a[f(x)] = (a[f(x)] ?? 0) + 1), a), {});
const badges = listings.map((m) => priceBadge(m.listing.price_cad, m.reference_price_cad));

describe("mock data", () => {
  it("has the planned counts", () => {
    expect(sellers).toHaveLength(6);
    expect(garageSales).toHaveLength(7);
    expect(listings).toHaveLength(20); // 2 photographed heroes + 18 real splats
    expect(orders).toHaveLength(2);
    expect(Object.keys(count(listings, (m) => m.category)).sort()).toEqual(
      ["clothing_accessories", "electronics", "furniture", "garden_plants", "home_kitchen", "sports_outdoors", "toys_games"]);
  });
  it("matches badge, grade, status distributions", () => {
    expect(count(badges, (b) => b.kind)).toEqual({ great: 6, fair: 8, high: 4, overpriced: 1, unknown: 1 });
    expect(count(listings, (m) => m.listing.condition_grade)).toEqual({ like_new: 7, light_wear: 10, moderate_wear: 2, heavy_wear: 1 });
    expect(count(listings, (m) => m.status)).toEqual({ available: 13, reserved: 4, sold: 3 });
    expect(listings.filter((m) => m.listing.needs_seller_check)).toHaveLength(1);
    for (const m of listings) expect(m.listing.needs_seller_check).toBe(m.listing.seller_check_reasons.length > 0);
  });
  it("has referential integrity", () => {
    const ids = listings.map((m) => m.listing.item_id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(garageSales.map((s) => s.id)).size).toBe(garageSales.length);
    for (const m of listings) {
      expect(sellers.some((s) => s.id === m.seller_id)).toBe(true);
      const sale = garageSales.find((s) => s.id === m.garage_sale_id);
      expect(sale?.seller_id).toBe(m.seller_id);
      expect(m.frames).toHaveLength(24);
      expect(m.listing.price_cad % 5).toBe(0);
    }
    for (const s of garageSales) {
      expect(sellers.some((x) => x.id === s.seller_id)).toBe(true);
      expect(listings.some((m) => m.garage_sale_id === s.id)).toBe(true);
    }
    for (const o of orders) expect(ids).toContain(o.item_id);
  });
  it("has one ended sale holding the sold items, except the demo seller's sale history, and a mix of delivery", () => {
    const ended = garageSales.filter((s) => s.ends_at < "2026-10-17");
    expect(ended).toHaveLength(1);
    const sold = listings.filter((x) => x.status === "sold");
    for (const m of sold.filter((x) => x.seller_id !== "sel_raj")) expect(m.garage_sale_id).toBe(ended[0].id);
    for (const m of sold.filter((x) => x.seller_id === "sel_raj")) expect(m.garage_sale_id).toBe("gs_agincourt_tech");
    expect(garageSales.some((s) => s.ships)).toBe(true);
    expect(garageSales.some((s) => !s.ships)).toBe(true);
  });
  it("streams real splats from SuperSplat and shows frames rendered from them; the heroes keep their photos", () => {
    for (const m of listings.slice(2)) {
      expect(m.splat_url).toMatch(/^https:\/\/d28zzqy0iyovbz\.cloudfront\.net\/[0-9a-f]{8}\/v\d\/meta\.json(#.*)?$/);
      const key = m.listing.item_id.slice(4).replace(/_/g, "-");
      const nums = m.frames.map((f) => Number(f.match(new RegExp(`^/demo/splats/${key}/f(\\d{2})\\.webp$`))?.[1]));
      expect(nums.every((x, n) => x === (nums[0] + n) % 24)).toBe(true); // one continuous turn of the 24 rendered frames
      expect(m.listing.attributes["3D scan"]).toMatch(/on SuperSplat, CC BY(-SA)? 4\.0$/);
    }
    expect(listings[0].listing.item_id).toBe("pots_i1");
    expect(listings[0].frames[23]).toBe("/local/pots/f23.webp");
    expect(listings[1].frames[0]).toBe("/local/zen/f00.webp");
    expect(frameFallbacks.pots_i1).toHaveLength(24);
    expect(frameFallbacks.zen_i1).toHaveLength(24);
  });
  it("seeds a meetup and a delivered order that verify", () => {
    expect(orders.map((o) => o.status)).toEqual(["reserved", "delivered"]);
    expect(orders.map((o) => o.method)).toEqual(["meetup", "shipping"]);
    for (const o of orders) expect(o.total_cad).toBe(o.price_cad + o.shipping_cad);
    expect(verifySample.explanation?.headline).toBeTruthy();
    expect(verifySample.comparison_id).toBe("fc4b95cb");
  });
  it("gives the demo seller a sale history: 2 sold, 1 reserved, 2 available", () => {
    const raj = listings.filter((m) => m.seller_id === "sel_raj");
    expect(raj).toHaveLength(5);
    expect(count(raj, (m) => m.status)).toEqual({ available: 2, reserved: 1, sold: 2 });
  });
  it("gives every seller reserved fictional demo contacts", () => {
    expect(sellersJson).toHaveLength(6);
    for (const x of sellersJson as { email?: string; phone?: string }[]) {
      expect(x.email).toMatch(/^[a-z]+@example\.com$/);
      expect(x.phone).toMatch(/^416-555-01\d\d$/);
    }
  });
  it("keeps the seller app's mock copies equal to the buyer entries", () => {
    const raj = (listingsRaw as { seller_id: string }[]).filter((m) => m.seller_id === "sel_raj");
    expect(readJson("../../seller/mock/my-listings.json")).toEqual(raj);
  });
});

describe("recorded comparison results", () => {
  it.each(RUN_PREFIXES)("%s parses and has a verdict", (prefix) => {
    const r = readJson(`../mock/compare/${prefix}.json`);
    expect(r.status).toBe("done");
    expect(r.verdict.label).toBeTruthy();
    expect(r.comparison_id.startsWith(prefix)).toBe(true);
    expect(r.timings_ms.total).toBeGreaterThan(0);
  });
  it.skipIf(!RUN_PREFIXES.every(runDir))("are exact byte copies of multiagent/runs/<run>/response.json", () => {
    for (const prefix of RUN_PREFIXES) {
      const copy = readFileSync(file(`../mock/compare/${prefix}.json`));
      const source = readFileSync(new URL(`${runDir(prefix)}/response.json`, RUNS));
      expect(copy.equals(source)).toBe(true);
    }
  });
});
