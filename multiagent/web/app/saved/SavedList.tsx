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
      <p className="py-12 text-center text-ink-2">
        Tap the heart on anything you like. It waits here.{" "}
        <Link href="/" className="text-mint-ink underline">Browse listings</Link>
      </p>
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
