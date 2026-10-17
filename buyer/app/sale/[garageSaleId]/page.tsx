import { notFound } from "next/navigation";
import GarageSaleHeader from "@/components/GarageSaleHeader";
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import SaveButton from "@/components/SaveButton";
import { getGarageSale, getGarageSales, getListings, getSeller } from "@/lib/data";
import { formatPrice } from "@/lib/format";

export async function generateStaticParams() {
  return (await getGarageSales()).map((s) => ({ garageSaleId: s.id }));
}

export default async function SalePage({ params }: { params: Promise<{ garageSaleId: string }> }) {
  const { garageSaleId } = await params;
  const sale = await getGarageSale(garageSaleId);
  const seller = sale && (await getSeller(sale.seller_id));
  if (!sale || !seller) notFound();
  const items = (await getListings()).filter((m) => m.garage_sale_id === sale.id);
  const open = items.filter((m) => m.status === "available");
  const total = open.reduce((n, m) => n + m.listing.price_cad, 0);
  return (
    <>
      <div>
        <GarageSaleHeader sale={sale} seller={seller} total={items.length} available={open.length} />
      </div>
      <section className="py-8 md:py-12">
        <p className="max-w-[62ch] text-[length:var(--t-lg)]">{sale.blurb}</p>
        <ul className="mb-8 mt-4 flex list-none flex-wrap gap-2 p-0 text-sm">
          {[sale.ships ? "Pickup or shipping" : "Pickup only", `${sale.pickup_slots.length} pickup slots`, `Available items total ${formatPrice(total)}`].map((t) => (
            <li key={t} className="rounded-sm bg-surface-2 px-2.5 py-1">{t}</li>
          ))}
        </ul>
        {items.length ? (
          <ListingGrid label={`Items in ${sale.name}`}>
            {items.map((m) => (
              <ListingCard key={m.listing.item_id} item={m} seller={seller} sale={sale}
                saveSlot={<SaveButton itemId={m.listing.item_id} title={m.listing.title} />} />
            ))}
          </ListingGrid>
        ) : (
          <div className="rounded-lg border border-dashed border-line px-6 py-14 text-center">
            <p className="font-display text-[length:var(--t-xl)] font-bold">This sale is being set up.</p>
            <p className="mt-2 text-ink-2">Check back soon.</p>
          </div>
        )}
      </section>
    </>
  );
}
