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
    <div className="flex flex-col gap-10 py-8 md:py-12">
      <header className="flex flex-col gap-3">
        <h1 className="text-[length:var(--t-2xl)] font-bold md:text-[length:var(--t-3xl)]">{seller.name}</h1>
        <p className="text-sm text-ink-2">Member since {seller.member_since}</p>
        <div className="max-w-[480px]"><SellerCard seller={seller} /></div>
      </header>
      <section aria-labelledby="sales">
        <h2 id="sales" className="mb-4 text-[length:var(--t-xl)] font-bold">Garage sales</h2>
        {sales.length ? (
          <ul className="flex list-none flex-col gap-2 p-0">
            {sales.map((s) => (
              <li key={s.id}>
                <Link href={`/sale/${s.id}`} className="flex min-h-12 items-center justify-between gap-3 rounded-md bg-surface px-4 hover:border-ink-2">
                  <span className="font-semibold">{s.name}</span>
                  <span className="text-sm text-ink-2">{s.location.neighbourhood}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : <p className="rounded-md border border-dashed border-line p-4 text-ink-2">No sales yet.</p>}
      </section>
      <section aria-labelledby="avail">
        <h2 id="avail" className="mb-4 text-[length:var(--t-xl)] font-bold">Available now</h2>
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
        ) : <p className="rounded-md border border-dashed border-line p-4 text-ink-2">Nothing available right now. Check back after their next sale.</p>}
      </section>
    </div>
  );
}
