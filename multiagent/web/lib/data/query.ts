import { dealRatio, priceBadge } from "../price-badge";
import type { Category, Grade, MarketListing } from "../types";

export type Sort = "newest" | "price_asc" | "price_desc" | "best_deal";
export interface ListingQuery {
  search?: string;
  cat?: Category;
  cond?: Grade;
  fair?: boolean; // only great or fair prices
  delivery?: "meetup" | "shipping"; // meetup = everything; shipping = sale ships
  sort?: Sort;
}
/** garage_sale_id -> sale ships. Needed only for the delivery filter. */
export type ShipsBySale = Record<string, boolean>;

const haystack = (m: MarketListing) =>
  [m.listing.title, m.listing.description, ...m.listing.tags, ...Object.values(m.listing.attributes)].join(" ").toLowerCase();

export function applyQuery(all: readonly MarketListing[], q: ListingQuery = {}, ships: ShipsBySale = {}): MarketListing[] {
  const terms = (q.search ?? "").toLowerCase().split(/\s+/).filter(Boolean);
  const out = all.filter((m) => {
    if (q.cat && m.category !== q.cat) return false;
    if (q.cond && m.listing.condition_grade !== q.cond) return false;
    if (q.fair) {
      const k = priceBadge(m.listing.price_cad, m.reference_price_cad).kind;
      if (k !== "great" && k !== "fair") return false;
    }
    if (q.delivery === "shipping" && !ships[m.garage_sale_id]) return false;
    if (terms.length) {
      const h = haystack(m);
      if (!terms.every((t) => h.includes(t))) return false;
    }
    return true;
  });
  const by: Record<Sort, (a: MarketListing, b: MarketListing) => number> = {
    newest: (a, b) => b.listed_at.localeCompare(a.listed_at),
    price_asc: (a, b) => a.listing.price_cad - b.listing.price_cad,
    price_desc: (a, b) => b.listing.price_cad - a.listing.price_cad,
    best_deal: (a, b) =>
      dealRatio(a.listing.price_cad, a.reference_price_cad) - dealRatio(b.listing.price_cad, b.reference_price_cad),
  };
  // stable: ties keep input order; Infinity - Infinity is NaN so guard
  return out.sort((a, b) => by[q.sort ?? "newest"](a, b) || 0);
}
