import Link from "next/link";
import type { ReactNode } from "react";
import type { GarageSale, MarketListing, Seller } from "@/lib/types";
import { formatPrice } from "@/lib/format";
import SpinViewer from "./SpinViewer";
import PriceBadge from "./PriceBadge";
import ConditionPill from "./ConditionPill";
import { Avatar } from "./SellerCard";

const firstSentence = (s: string) => s.split(/(?<=[.!?])\s/)[0] ?? s;

export default function ListingCard({
  item,
  seller,
  sale,
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
    <article className="relative flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-ink-2 hover:shadow-[var(--shadow-hover)] motion-reduce:hover:translate-y-0">
      <div className={`relative aspect-square bg-surface-2 ${available ? "" : "opacity-60"}`}>
        <SpinViewer frames={item.frames} alt={l.title} variant="card" viewerUrl={l.viewer_url} />
      </div>
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
      <div className="flex flex-1 flex-col gap-2 p-3 md:p-4">
        <div className="flex flex-col items-start gap-1 md:flex-row md:items-center md:justify-between md:gap-2">
          <span className="font-display text-xl font-bold leading-none tabular-nums md:text-2xl">{formatPrice(l.price_cad)}</span>
          <PriceBadge price={l.price_cad} reference={item.reference_price_cad} />
        </div>
        <h3 className="line-clamp-2 text-base font-semibold leading-snug md:text-lg">
          <Link
            href={`/listing/${l.item_id}`}
            className="after:absolute after:inset-0 after:rounded-md focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-offset-2 focus-visible:after:outline-focus"
          >
            {l.title}
          </Link>
        </h3>
        <p className="line-clamp-2 hidden text-sm text-ink-2 md:block">{firstSentence(l.description)}</p>
        <div className="mt-auto pt-1">
          <ConditionPill grade={l.condition_grade} sellerChecking={l.needs_seller_check} />
        </div>
        {available && (
          <Link href={`/listing/${l.item_id}#reserve`} className="btn-primary relative z-10 mt-1 hidden w-full md:flex">
            Reserve
          </Link>
        )}
      </div>
      <Link href={`/sale/${sale.id}`} className="relative z-10 flex items-center gap-2 border-t border-line px-3 py-2.5 transition-colors hover:bg-surface-2 md:px-4">
        <Avatar seller={seller} />
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">{seller.name}</span>
          <span className="block truncate text-xs text-ink-2">
            {sale.name} · {sale.location.neighbourhood}
          </span>
        </span>
      </Link>
    </article>
  );
}
