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
    expect(garageSales).toHaveLength(8);
    expect(listings).toHaveLength(40);
    expect(orders).toHaveLength(2);
    expect(count(listings, (m) => m.category)).toEqual(Object.fromEntries(Object.keys(count(listings, (m) => m.category)).map((k) => [k, 5])));
    expect(Object.keys(count(listings, (m) => m.category))).toHaveLength(8);
  });
  it("matches badge, grade, status distributions", () => {
    expect(count(badges, (b) => b.kind)).toEqual({ great: 12, fair: 16, high: 7, overpriced: 3, unknown: 2 });
    expect(count(listings, (m) => m.listing.condition_grade)).toEqual({ like_new: 10, light_wear: 16, moderate_wear: 10, heavy_wear: 4 });
    expect(count(listings, (m) => m.status)).toEqual({ available: 31, reserved: 5, sold: 4 });
    expect(listings.filter((m) => m.listing.needs_seller_check)).toHaveLength(4);
    for (const m of listings) expect(m.listing.needs_seller_check).toBe(m.listing.seller_check_reasons.length > 0);
  });
  it("sits exactly on the badge boundaries", () => {
    const ratios = listings.filter((m) => m.reference_price_cad).map((m) => m.listing.price_cad / m.reference_price_cad!);
    for (const r of [0.85, 1.1, 1.3]) expect(ratios.some((x) => Math.abs(x - r) < 1e-9)).toBe(true);
  });
  it("has referential integrity", () => {
    const ids = listings.map((m) => m.listing.item_id);
    expect(new Set(ids).size).toBe(40);
    expect(new Set(garageSales.map((s) => s.id)).size).toBe(8);
    for (const m of listings) {
      expect(sellers.some((s) => s.id === m.seller_id)).toBe(true);
      const sale = garageSales.find((s) => s.id === m.garage_sale_id);
      expect(sale?.seller_id).toBe(m.seller_id);
      expect(m.frames).toHaveLength(24);
      expect(m.listing.price_cad % 5).toBe(0);
    }
    for (const s of garageSales) {
      expect(sellers.some((x) => x.id === s.seller_id)).toBe(true);
      expect(listings.filter((m) => m.garage_sale_id === s.id)).toHaveLength(5);
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
  it("uses turntable URLs, with local heroes and fallbacks", () => {
    for (const m of listings.slice(2)) expect(m.frames.every((f, n) => new RegExp(`^/frames/[a-z]+/[a-z]+/${n}$`).test(f))).toBe(true);
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
    expect(readJson("../../seller/mock/scan-result.json")).toEqual(listings.find((m) => m.listing.item_id === "pots_i1"));
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
