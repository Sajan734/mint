import Link from "next/link";
import type { ReactNode } from "react";
import type { GarageSale, MarketListing, Seller } from "@/lib/types";
import { formatPrice } from "@/lib/format";
import PriceBadge from "./PriceBadge";
import CardMedia from "./CardMedia";

// Marketplace card: photo (3D on hover), price + fair-price rating, title. The whole card is one link.
// `seller` and `sale` stay in the props so every page keeps compiling; the card no longer shows them.
export default function ListingCard({
  item,
  saveSlot,
}: {
  item: MarketListing;
  seller: Seller;
  sale: GarageSale;
  saveSlot?: ReactNode;
}) {
  const { listing: l } = item;
  const available = item.status === "available";
  return (
    <CardMedia
      item={item}
      className="relative flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-ink-2 hover:shadow-[var(--shadow-hover)] motion-reduce:hover:translate-y-0"
    >
      <span
        className="pointer-events-none absolute left-2 top-2 inline-flex items-center gap-1 rounded-full border border-line-strong bg-surface px-2 py-1 font-mono text-xs leading-none text-ink"
        title="Scan views"
      >
        <svg aria-hidden viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="var(--mint-ink)" strokeWidth="3">
          <circle cx="12" cy="12" r="8" strokeDasharray="5 3" />
        </svg>
        {item.usable_view_count} views
      </span>
      {!available && (
        <span className="absolute left-2 top-10 rounded-sm border border-line-strong bg-surface px-2 py-0.5 text-sm font-semibold text-ink">
          {item.status === "sold" ? "Sold" : "Reserved"}
        </span>
      )}
      {saveSlot && <div className="absolute right-2 top-2 z-10">{saveSlot}</div>}
      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-display text-xl font-bold leading-none tabular-nums">{formatPrice(l.price_cad)}</span>
          <PriceBadge price={l.price_cad} reference={item.reference_price_cad} />
        </div>
        <h3 className="line-clamp-2 text-base font-semibold leading-snug">
          <Link
            href={`/listing/${l.item_id}`}
            className="after:absolute after:inset-0 after:rounded-md focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-offset-2 focus-visible:after:outline-focus"
          >
            {l.title}
          </Link>
        </h3>
      </div>
    </CardMedia>
  );
}
