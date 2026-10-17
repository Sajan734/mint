import Link from "next/link";
import { Suspense } from "react";
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
import HeroScan from "@/components/HeroScan";

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

// Real spin frames of the scan in the hero (buyer/public/demo/listings/a6816dfc/spin): what "scanned in 3D" means.
const SPIN = [0, 4, 8, 12, 16, 20].map((n) => `/demo/listings/a6816dfc/spin/f${String(n).padStart(2, "0")}.webp`);

const STEPS = [
  {
    title: "Scanned on the seller's phone",
    body: "The seller turns the item on a sheet of paper while the Mint app films it. Mint builds a 3D model you can turn on any phone, so no side stays hidden.",
  },
  {
    title: "A price you can check",
    body: "Mint names the item, writes the listing and compares the asking price with what the same thing sells for used. The badge tells you if it is fair.",
  },
  {
    title: "Checked again at pickup",
    body: "When you meet, scan it again. Mint compares your scan with the seller's, view by view, before any money changes hands.",
  },
];

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
    <div className="flex flex-col gap-20 md:gap-28">
      {browsing && (
        <>
          <section aria-labelledby="intro-h" className="grid items-center gap-10 pt-4 md:grid-cols-[1.15fr_1fr] md:gap-14 md:pt-10">
            <div className="rise-load flex flex-col items-start gap-6">
              <h1 id="intro-h" className="max-w-[12ch] text-[length:var(--t-3xl)] leading-[0.98] tracking-[-0.03em]">
                Good finds from down the street.
              </h1>
              <p className="max-w-[46ch] text-[length:var(--t-lg)] leading-relaxed">
                Your neighbours scan each item in 3D on their phone. Turn it, look at every side, and see if the price
                is fair before you meet.
              </p>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                <a href="#items-h" className="btn-primary">
                  Browse {pool.length} items
                </a>
                <a href="/sell" className="inline-flex min-h-11 items-center font-semibold text-leaf underline-offset-4 hover:underline">
                  Sell something of yours
                </a>
              </div>
            </div>
            <HeroScan />
          </section>
          <JustListed sellers={sellers} sales={sales} />
          {picks.length > 0 && (
            <Rail id="picks-h" title="Picked for you" note="One of each kind of thing, newest first.">
              {cardsFor(picks, sellerById, saleById)}
            </Rail>
          )}
          <section aria-labelledby="how-h" className="rise -mx-4 grid gap-10 bg-pine px-5 py-14 text-on-pine sm:-mx-6 sm:px-8 md:mx-0 md:rounded-[32px] md:px-12 md:py-16 lg:grid-cols-[1fr_1.1fr] lg:gap-16">
            <div className="flex flex-col gap-8">
              <h2 id="how-h" className="max-w-[14ch] text-[length:var(--t-2xl)] text-on-pine md:text-[2.75rem]">
                Bought from a neighbour, seen from every side.
              </h2>
              <ul className="flex list-none flex-col gap-6 p-0">
                {STEPS.map((st) => (
                  <li key={st.title} className="flex max-w-[52ch] flex-col gap-1">
                    <h3 className="text-lg font-semibold text-on-pine">{st.title}</h3>
                    <p className="text-on-pine-2">{st.body}</p>
                  </li>
                ))}
              </ul>
              <Link href="/about" className="inline-flex min-h-11 w-fit items-center font-semibold text-leaf underline-offset-4 hover:underline">
                How Mint works
              </Link>
            </div>
            <figure className="flex flex-col gap-3 self-center">
              <ul aria-label="Six views from one real scan" className="grid list-none grid-cols-3 gap-2 p-0 sm:gap-3">
                {SPIN.map((src, i) => (
                  <li key={src} className="aspect-square overflow-hidden rounded-[16px] bg-bg">
                    {/* eslint-disable-next-line @next/next/no-img-element -- real spin frames from /public */}
                    <img src={src} alt={`View ${i + 1}`} className="h-full w-full object-contain p-2" loading="lazy" />
                  </li>
                ))}
              </ul>
              <figcaption className="text-sm text-on-pine-2">Six of the 24 views from the scan at the top of the page.</figcaption>
            </figure>
          </section>
          {deals.length > 0 && (
            <Rail
              id="deals-h"
              title="Great deals"
              note="Priced at or below what Mint says is fair."
              action={
                <Link href="/?fair=1&sort=best_deal#items-h" className="inline-flex min-h-11 items-center font-semibold text-leaf underline-offset-4 hover:underline">
                  See all deals
                </Link>
              }
            >
              {cardsFor(deals, sellerById, saleById)}
            </Rail>
          )}
          {tiles.length > 0 && (
            <section aria-labelledby="sales-h" className="rise grid gap-6 lg:grid-cols-[0.8fr_1.5fr] lg:gap-14">
              <div className="flex flex-col gap-2">
                <h2 id="sales-h" className="text-[length:var(--t-xl)] md:text-[length:var(--t-2xl)]">Garage sales near you</h2>
                <p className="max-w-[36ch] text-ink-2">Walk over, or reserve something first and pick it up on the day.</p>
              </div>
              <GarageSaleRail tiles={tiles} />
            </section>
          )}
        </>
      )}
      <section aria-labelledby="items-h" className="flex scroll-mt-24 flex-col gap-5">
        {q ? (
          <h1 id="items-h" className="text-[length:var(--t-xl)] md:text-[length:var(--t-2xl)]">Results for “{q}”</h1>
        ) : (
          <h2 id="items-h" className="text-[length:var(--t-xl)] md:text-[length:var(--t-2xl)]">Everything for sale</h2>
        )}
        <Suspense>
          <FilterBar />
        </Suspense>
        <p role="status" className="text-sm text-ink-2">
          {items.length} {items.length === 1 ? "item" : "items"}
        </p>
        {items.length === 0 ? (
          <div className="flex flex-col items-start gap-4 rounded-[24px] bg-surface p-8">
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
