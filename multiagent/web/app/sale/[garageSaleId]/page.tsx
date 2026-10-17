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
      <div className="-mx-4 md:-mx-6 lg:-mx-8">
        <GarageSaleHeader sale={sale} seller={seller} total={items.length} available={open.length} />
      </div>
      <section className="py-6">
        <p className="mb-1 text-ink-2">{sale.blurb}</p>
        <p className="mb-4 text-sm text-ink-2">
          {sale.ships ? "Pickup or shipping" : "Pickup only"} · {sale.pickup_slots.length} pickup slots · Available items total {formatPrice(total)}
        </p>
        {items.length ? (
          <ListingGrid label={`Items in ${sale.name}`}>
            {items.map((m) => (
              <ListingCard key={m.listing.item_id} item={m} seller={seller} sale={sale}
                saveSlot={<SaveButton itemId={m.listing.item_id} title={m.listing.title} />} />
            ))}
          </ListingGrid>
        ) : (
          <p className="py-12 text-center text-ink-2">This sale is being set up. Check back soon.</p>
        )}
      </section>
    </>
  );
}
