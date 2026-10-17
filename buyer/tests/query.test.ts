import { describe, expect, it } from "vitest";
import { applyQuery } from "../lib/data/query";
import { garageSales, listings } from "../lib/data/mock";
import { priceBadge } from "../lib/price-badge";

const ships = Object.fromEntries(garageSales.map((s) => [s.id, s.ships]));

describe("applyQuery", () => {
  it("returns everything with no query", () => expect(applyQuery(listings)).toHaveLength(20));
  it("filters by category and condition", () => {
    expect(applyQuery(listings, { cat: "toys_games" })).toHaveLength(6);
    const r = applyQuery(listings, { cond: "heavy_wear" });
    expect(r.map((m) => m.listing.item_id)).toEqual(["itm_nike"]);
  });
  it("fair filter keeps only great or fair", () => {
    const r = applyQuery(listings, { fair: true });
    expect(r).toHaveLength(14);
    expect(r.every((m) => ["great", "fair"].includes(priceBadge(m.listing.price_cad, m.reference_price_cad).kind))).toBe(true);
  });
  it("delivery=shipping keeps listings from shipping sales", () => {
    const r = applyQuery(listings, { delivery: "shipping" }, ships);
    expect(r.length).toBeGreaterThan(0);
    expect(r.length).toBeLessThan(listings.length);
    expect(r.every((m) => ships[m.garage_sale_id])).toBe(true);
    expect(applyQuery(listings, { delivery: "meetup" }, ships)).toHaveLength(listings.length);
  });
  it("search is case-insensitive over title, tags, description, attributes", () => {
    expect(applyQuery(listings, { search: "CAMERA" }).map((m) => m.listing.item_id).sort()).toEqual(["itm_lens", "itm_sony_a7"]);
    expect(applyQuery(listings, { search: "succulents" })[0].listing.item_id).toBe("pots_i1");
    expect(applyQuery(listings, { search: "lego yellow" }).map((m) => m.listing.item_id)).toEqual(["itm_lego_bulldozer"]); // title + attribute
    expect(applyQuery(listings, { search: "zzzz" })).toEqual([]);
  });
  it("sorts", () => {
    const asc = applyQuery(listings, { sort: "price_asc" }).map((m) => m.listing.price_cad);
    expect(asc).toEqual([...asc].sort((a, b) => a - b));
    const desc = applyQuery(listings, { sort: "price_desc" }).map((m) => m.listing.price_cad);
    expect(desc).toEqual([...desc].sort((a, b) => b - a));
    const deal = applyQuery(listings, { sort: "best_deal" });
    expect(priceBadge(deal[0].listing.price_cad, deal[0].reference_price_cad).kind).toBe("great");
    expect(deal.at(-1)?.reference_price_cad).toBeNull();
    const newest = applyQuery(listings, { sort: "newest" }).map((m) => m.listed_at);
    expect(newest).toEqual([...newest].sort().reverse());
  });
  it("does not mutate input", () => {
    const before = listings.map((m) => m.listing.item_id).join();
    applyQuery(listings, { sort: "price_desc" });
    expect(listings.map((m) => m.listing.item_id).join()).toBe(before);
  });
});
