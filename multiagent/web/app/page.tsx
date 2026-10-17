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

  return (
    <div className="flex flex-col gap-8 py-6">
      <section>
        <h1 className="font-display text-[length:var(--t-2xl)] font-bold">Second-hand, scanned in 360.</h1>
        <p className="text-ink-2">Every price is checked against what the item is really worth.</p>
      </section>
      <section aria-labelledby="sales-h" className="flex flex-col gap-3">
        <h2 id="sales-h" className="text-xl font-semibold">Garage sales near you</h2>
        <GarageSaleRail tiles={tiles} />
      </section>
      <section aria-labelledby="items-h" className="flex flex-col gap-4">
        <h2 id="items-h" className="sr-only">Items</h2>
        <Suspense>
          <FilterBar />
        </Suspense>
        <p role="status" className="text-sm text-ink-2">
          {items.length} {items.length === 1 ? "item" : "items"}
        </p>
        {items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="text-lg">Nothing here yet. Try a wider search.</p>
            <Link href="/" className="inline-flex h-11 items-center rounded-md bg-ink px-5 font-semibold text-bg">
              Clear filters
            </Link>
          </div>
        ) : (
          <ListingGrid label="Items for sale">
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
