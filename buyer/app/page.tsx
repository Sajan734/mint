import Link from "next/link";
import { Suspense, type ReactNode } from "react";
import { getGarageSales, getListings, getSellers } from "@/lib/data";
import type { Category, GarageSale, Grade, MarketListing, Seller } from "@/lib/types";
import type { Sort } from "@/lib/data/query";
import { dealRatio, priceBadge } from "@/lib/price-badge";
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import GarageSaleRail from "@/components/GarageSaleRail";
import FilterBar from "@/components/FilterBar";
import SaveButton from "@/components/SaveButton";
import JustListed, { Rail } from "@/components/JustListed";

type Params = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

const SHELF = 8; // cards per suggestion row
const PAGE = 12; // Fresh scans page size
// The demo buyer is also the demo seller: never suggest their own items. Same as DEMO_SELLER_ID in lib/mock-mode.ts
// (a client module, so its exports are not plain values here).
const ME = "sel_raj";

/** Great or fair price, best deal first. */
const greatDeals = (pool: MarketListing[]) =>
  pool
    .filter((m) => ["great", "fair"].includes(priceBadge(m.listing.price_cad, m.reference_price_cad).kind))
    .sort((a, b) => dealRatio(a.listing.price_cad, a.reference_price_cad) - dealRatio(b.listing.price_cad, b.reference_price_cad))
    .slice(0, SHELF);

/** No history to personalise on yet, so: a spread of categories, newest first, nothing already in Great deals, and
 *  nothing Mint calls overpriced. */
function recommended(pool: MarketListing[], skip: MarketListing[]) {
  const byCategory = new Map<Category, MarketListing>();
  for (const m of [...pool].sort((a, b) => b.listed_at.localeCompare(a.listed_at))) {
    if (skip.includes(m) || byCategory.has(m.category)) continue;
    if (priceBadge(m.listing.price_cad, m.reference_price_cad).kind !== "overpriced") byCategory.set(m.category, m);
  }
  return [...byCategory.values()].slice(0, SHELF);
}

function cardsFor(list: MarketListing[], sellerById: Map<string, Seller>, saleById: Map<string, GarageSale>) {
  return list.flatMap((m) => {
    const seller = sellerById.get(m.seller_id);
    const sale = saleById.get(m.garage_sale_id);
    if (!seller || !sale) return [];
    return [
      <ListingCard
        key={m.listing.item_id} item={m} seller={seller} sale={sale}
        saveSlot={<SaveButton itemId={m.listing.item_id} title={m.listing.title} />}
      />,
    ];
  });
}

const Pledge = ({ icon, children }: { icon: ReactNode; children: string }) => (
  <li className="flex min-h-6 items-center gap-1.5">
    <svg aria-hidden viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--mint-ink)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      {icon}
    </svg>
    {children}
  </li>
);

export default async function Home({ searchParams }: { searchParams: Promise<Params> }) {
  const p = await searchParams;
  const q = one(p.q)?.trim() || undefined;
  const [all, sales, sellers] = await Promise.all([getListings(), getGarageSales(), getSellers()]);
  const items = await getListings({
    search: q,
    cat: one(p.cat) as Category | undefined,
    cond: one(p.cond) as Grade | undefined,
    fair: one(p.fair) === "1",
    delivery: one(p.delivery) === "shipping" ? "shipping" : undefined,
    sort: one(p.sort) as Sort | undefined,
  });
  const sellerById = new Map(sellers.map((s) => [s.id, s]));
  const saleById = new Map(sales.map((s) => [s.id, s]));
  const tiles = sales.flatMap((sale) => {
    const mine = all.filter((m) => m.garage_sale_id === sale.id);
    const seller = sellerById.get(sale.seller_id);
    const cover = mine[0]?.frames[0];
    return seller && cover ? [{ sale, seller, cover, itemCount: mine.length }] : [];
  });

  const kept = (["cat", "cond", "fair", "delivery", "sort"] as const).flatMap((k) => one(p[k]) ?? []);
  const filterKey = JSON.stringify([q, ...kept]);
  // Shelves belong to browsing. A search shows its results first, and filters never move the page under the user.
  const browsing = !q;
  const pool = all.filter((m) => m.status === "available" && m.seller_id !== ME);
  const deals = greatDeals(pool);
  const picks = recommended(pool, deals);

  return (
    <div className="flex flex-col gap-8 md:gap-10">
      {browsing && (
        <>
          <section aria-labelledby="intro-h" className="flex flex-col gap-2 border-b border-line pb-4 md:flex-row md:items-center md:justify-between md:gap-6">
            <h1 id="intro-h" className="text-[length:var(--t-lg)] font-bold tracking-tight md:text-[length:var(--t-xl)]">
              Second-hand finds, scanned and priced fairly.
            </h1>
            <ul aria-label="Our promises" className="flex flex-wrap gap-x-5 gap-y-1 text-sm font-medium">
              <Pledge icon={<circle cx="12" cy="12" r="8" strokeDasharray="5 3" />}>Every item is a 360° scan</Pledge>
              <Pledge icon={<path d="m5 12 5 5 9-10" />}>Fair price, checked</Pledge>
            </ul>
          </section>
          <JustListed sellers={sellers} sales={sales} />
          {picks.length > 0 && (
            <Rail id="picks-h" title="Recommended for you">
              {cardsFor(picks, sellerById, saleById)}
            </Rail>
          )}
          {deals.length > 0 && (
            <Rail
              id="deals-h"
              title="Great deals"
              action={
                <Link href="/?fair=1&sort=best_deal#items-h" className="inline-flex min-h-11 items-center text-sm font-semibold text-mint-ink underline-offset-2 hover:underline">
                  See all deals
                </Link>
              }
            >
              {cardsFor(deals, sellerById, saleById)}
            </Rail>
          )}
          <section aria-labelledby="sales-h" className="flex flex-col gap-3">
            <h2 id="sales-h" className="text-[length:var(--t-xl)] font-bold tracking-tight">Garage sales near you</h2>
            <GarageSaleRail tiles={tiles} />
          </section>
        </>
      )}
      <section aria-labelledby="items-h" className="flex scroll-mt-20 flex-col gap-4">
        {q ? (
          <h1 id="items-h" className="text-[length:var(--t-xl)] font-bold tracking-tight">Results for “{q}”</h1>
        ) : (
          <h2 id="items-h" className="text-[length:var(--t-xl)] font-bold tracking-tight">Fresh scans</h2>
        )}
        <Suspense>
          <FilterBar />
        </Suspense>
        <p role="status" className="text-sm text-ink-2">
          {items.length} {items.length === 1 ? "item" : "items"}
        </p>
        {items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="text-lg">Nothing here yet. Try a wider search.</p>
            <Link href="/" className="btn-primary">
              Clear filters
            </Link>
          </div>
        ) : (
          <ListingGrid key={filterKey} label="Items for sale" pageSize={PAGE}>
            {cardsFor(items, sellerById, saleById)}
          </ListingGrid>
        )}
      </section>
    </div>
  );
}
