import Link from "next/link";
import type { ReactNode } from "react";
import type { GarageSale, MarketListing, Seller } from "@/lib/types";
import { formatPrice } from "@/lib/format";
import PriceBadge from "./PriceBadge";
import CardMedia from "./CardMedia";

// Marketplace card (docs/design/DESIGN.md §4): no box. A shelf-coloured well with the scan (3D on hover), then price
// + fair-price rating, then the title. The whole card is one link.
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
      className="group relative flex h-full flex-col gap-3"
    >
      {!available && (
        <span className="pointer-events-none absolute left-2.5 top-2.5 rounded-full bg-raised px-3 py-1 text-[13px] font-semibold text-ink">
          {item.status === "sold" ? "Sold" : "Reserved"}
        </span>
      )}
      {saveSlot && <div className="absolute right-2.5 top-2.5 z-10">{saveSlot}</div>}
      <div className="flex flex-1 flex-col gap-1.5 px-0.5">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <span className="text-lg font-bold leading-none tabular-nums">{formatPrice(l.price_cad)}</span>
          <PriceBadge price={l.price_cad} reference={item.reference_price_cad} />
        </div>
        <h3 className="line-clamp-2 text-base font-medium leading-snug">
          <Link
            href={`/listing/${l.item_id}`}
            className="after:absolute after:inset-0 after:rounded-[16px] focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-offset-4 focus-visible:after:outline-focus"
          >
            {l.title}
          </Link>
        </h3>
      </div>
    </CardMedia>
  );
}
