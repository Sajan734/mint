import Link from "next/link";
import { notFound } from "next/navigation";
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import SaveButton from "@/components/SaveButton";
import SellerCard from "@/components/SellerCard";
import { getGarageSales, getListings, getSeller, getSellers } from "@/lib/data";

export async function generateStaticParams() {
  return (await getSellers()).map((s) => ({ id: s.id }));
}

export default async function SellerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const seller = await getSeller(id);
  if (!seller) notFound();
  // latest-ending first, so active sales lead (no Date.now: page is static)
  const sales = (await getGarageSales())
    .filter((s) => s.seller_id === id)
    .sort((a, b) => b.ends_at.localeCompare(a.ends_at));
  const items = (await getListings()).filter((m) => m.seller_id === id && m.status === "available");
  return (
    <div className="flex flex-col gap-8 py-6">
      <h1 className="sr-only">{seller.name}</h1>
      <SellerCard seller={seller} />
      <p className="text-sm text-ink-2">Member since {seller.member_since}</p>
      <section aria-labelledby="sales">
        <h2 id="sales" className="mb-3 text-xl font-bold">Garage sales</h2>
        {sales.length ? (
          <ul className="flex list-none flex-col gap-2 p-0">
            {sales.map((s) => (
              <li key={s.id}>
                <Link href={`/sale/${s.id}`} className="text-mint-ink hover:underline">{s.name}</Link>
                <span className="text-sm text-ink-2"> · {s.location.neighbourhood}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-ink-2">No sales yet.</p>}
      </section>
      <section aria-labelledby="avail">
        <h2 id="avail" className="mb-3 text-xl font-bold">Available now</h2>
        {items.length ? (
          <ListingGrid label={`Listings by ${seller.name}`}>
            {items.map((m) => {
              const sale = sales.find((s) => s.id === m.garage_sale_id);
              return sale ? (
                <ListingCard key={m.listing.item_id} item={m} seller={seller} sale={sale}
                  saveSlot={<SaveButton itemId={m.listing.item_id} title={m.listing.title} />} />
              ) : null;
            })}
          </ListingGrid>
        ) : <p className="text-ink-2">Nothing available right now.</p>}
      </section>
    </div>
  );
}
