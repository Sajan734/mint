"use client";
import Link from "next/link";
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import SaveButton from "@/components/SaveButton";
import { useStore } from "@/lib/store";
import type { GarageSale, MarketListing, Seller } from "@/lib/types";

export default function SavedList({ items, sellers, sales }: { items: MarketListing[]; sellers: Seller[]; sales: GarageSale[] }) {
  const { state } = useStore();
  const rows = items.flatMap((m) => {
    const seller = sellers.find((s) => s.id === m.seller_id);
    const sale = sales.find((s) => s.id === m.garage_sale_id);
    return state.saved.includes(m.listing.item_id) && seller && sale ? [{ m, seller, sale }] : [];
  });
  if (!rows.length)
    return (
      <div className="rounded-lg border border-dashed border-line px-6 py-14 text-center">
        <svg aria-hidden viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="1.75" className="mx-auto text-ink-2"><path d="M12 21s-7-4.4-9.3-9A5.3 5.3 0 0 1 12 6.6 5.3 5.3 0 0 1 21.3 12C19 16.6 12 21 12 21z" /></svg>
        <p className="mt-4 font-display text-[length:var(--t-xl)] font-bold">Nothing saved yet.</p>
        <p className="mx-auto mt-2 max-w-[40ch] text-ink-2">Tap the heart on anything you like. It waits here.</p>
        <Link href="/" className="mt-6 inline-flex min-h-11 items-center rounded-md bg-ink px-5 font-semibold text-bg">Browse listings</Link>
      </div>
    );
  return (
    <ListingGrid label="Saved listings">
      {rows.map(({ m, seller, sale }) => (
        <ListingCard key={m.listing.item_id} item={m} seller={seller} sale={sale}
          saveSlot={<SaveButton itemId={m.listing.item_id} title={m.listing.title} />} />
      ))}
    </ListingGrid>
  );
}
