import Link from "next/link";
import { Suspense } from "react";
import { getGarageSales, getListings, getSellers } from "@/lib/data";
import type { Category, Grade } from "@/lib/types";
import type { Sort } from "@/lib/data/query";
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import GarageSaleRail from "@/components/GarageSaleRail";
import FilterBar from "@/components/FilterBar";
import SaveButton from "@/components/SaveButton";

type Params = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export default async function Home({ searchParams }: { searchParams: Promise<Params> }) {
  const p = await searchParams;
  const [all, sales, sellers] = await Promise.all([getListings(), getGarageSales(), getSellers()]);
  const items = await getListings({
    search: one(p.q),
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

  const PAGE = 12;
  const kept = (["cat", "cond", "fair", "delivery", "sort"] as const).flatMap((k) => {
    const v = one(p[k]);
    return v ? [[k, v] as const] : [];
  });
  const filterKey = JSON.stringify([one(p.q), ...kept]);
  const peek = tiles.slice(0, 3);

  return (
    <div className="flex flex-col gap-10 md:gap-12">
      <section className="grid items-center gap-6 rounded-lg border border-line bg-surface px-5 py-8 md:grid-cols-[1.15fr_1fr] md:gap-10 md:px-10 md:py-12">
        <div className="flex flex-col gap-4">
          <h1 className="text-[length:var(--t-2xl)] font-bold tracking-tight md:text-[length:var(--t-3xl)]">
            Second-hand, scanned in 360.
          </h1>
          <p className="max-w-[46ch] text-lg text-ink-2">
            Turn it over, see the wear, and know the price is fair before you reserve. Proof, not photos.
          </p>
          <form role="search" action="/" className="flex max-w-lg gap-2">
            {kept.map(([k, v]) => <input key={k} type="hidden" name={k} value={v} />)}
            <label className="min-w-0 flex-1">
              <span className="sr-only">Search items</span>
              <input
                type="search" name="q" defaultValue={one(p.q) ?? ""} placeholder="Search items"
                className="h-12 w-full rounded-md border border-line-strong bg-bg px-4 placeholder:text-ink-2"
              />
            </label>
            <button type="submit" className="btn-primary h-12 shrink-0">Search</button>
          </form>
        </div>
        <div aria-hidden className="pad hidden h-64 items-end justify-center rounded-lg px-4 md:flex">
          {peek.map((t, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={t.sale.id} src={t.cover} alt="" className={`h-52 w-1/3 object-contain ${i === 1 ? "relative z-10 h-60 scale-110" : "opacity-95"}`} />
          ))}
        </div>
      </section>
      <section aria-labelledby="sales-h" className="flex flex-col gap-2">
        <h2 id="sales-h" className="text-[length:var(--t-xl)] font-bold tracking-tight">Garage sales near you</h2>
        <GarageSaleRail tiles={tiles} />
      </section>
      <section aria-labelledby="items-h" className="flex flex-col gap-4 scroll-mt-20">
        <h2 id="items-h" className="text-[length:var(--t-xl)] font-bold tracking-tight">Fresh scans</h2>
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
            {items.map((m) => {
              const seller = sellerById.get(m.seller_id);
              const sale = saleById.get(m.garage_sale_id);
              if (!seller || !sale) return null;
              return (
                <ListingCard
                  key={m.listing.item_id} item={m} seller={seller} sale={sale}
                  saveSlot={<SaveButton itemId={m.listing.item_id} title={m.listing.title} />}
                />
              );
            })}
          </ListingGrid>
        )}
      </section>
    </div>
  );
}
