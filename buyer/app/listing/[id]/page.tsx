import { notFound } from "next/navigation";
import { getGarageSale, getGarageSales, getListing, getListings, getSeller, getSellers } from "@/lib/data";
import type { MarketListing } from "@/lib/types";
import SaveButton from "@/components/SaveButton";
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import LocalListing, { ListingView } from "@/components/LocalListing";

// Ids outside this list (published on this device) render on demand: dynamicParams defaults to true in Next 16.
export async function generateStaticParams() {
  return (await getListings()).map((m) => ({ id: m.listing.item_id }));
}

async function Grid({ label, list }: { label: string; list: MarketListing[] }) {
  if (!list.length) return null;
  const cards = await Promise.all(
    list.map(async (m) => {
      const [s, g] = await Promise.all([getSeller(m.seller_id), getGarageSale(m.garage_sale_id)]);
      if (!s || !g) return null;
      return (
        <ListingCard
          key={m.listing.item_id}
          item={m}
          seller={s}
          sale={g}
          saveSlot={<SaveButton itemId={m.listing.item_id} title={m.listing.title} />}
        />
      );
    }),
  );
  return (
    <section className="mt-16">
      <h2 className="mb-4 text-[length:var(--t-xl)] font-bold">{label}</h2>
      <ListingGrid label={label}>{cards}</ListingGrid>
    </section>
  );
}

export default async function ListingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const item = await getListing(id);
  if (!item) {
    // Not in the catalog: it may be a listing published in this browser. The client checks its store.
    const [sellers, sales] = await Promise.all([getSellers(), getGarageSales()]);
    return <LocalListing id={id} sellers={sellers} sales={sales} />;
  }
  const [seller, sale, all] = await Promise.all([
    getSeller(item.seller_id),
    getGarageSale(item.garage_sale_id),
    getListings(),
  ]);
  if (!seller || !sale) notFound();
  const others = all.filter((m) => m.listing.item_id !== id);
  const more = others.filter((m) => m.garage_sale_id === sale.id).slice(0, 4);
  const similar = others.filter((m) => m.category === item.category && !more.includes(m)).slice(0, 4);

  return (
    <ListingView item={item} seller={seller} sale={sale}>
      <Grid label="More from this sale" list={more} />
      <Grid label="Similar items" list={similar} />
    </ListingView>
  );
}
