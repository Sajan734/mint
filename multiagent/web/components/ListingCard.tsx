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
    <article className="relative flex flex-col overflow-hidden rounded-md border border-line bg-surface transition-colors hover:border-ink-2 hover:shadow-[var(--shadow-hover)]">
      <div className={`relative aspect-square bg-surface-2 ${available ? "" : "opacity-60"}`}>
        <SpinViewer frames={item.frames} alt={l.title} variant="card" viewerUrl={l.viewer_url} />
      </div>
      <span className="pointer-events-none absolute left-2 top-2 rounded-full bg-surface px-2 py-0.5 font-mono text-xs" title="Scan views">
        {item.usable_view_count} views
      </span>
      {!available && (
        <span className="absolute left-2 top-10 rounded-sm bg-surface px-2 py-0.5 text-sm font-semibold text-ink">
          {item.status === "sold" ? "Sold" : "Reserved"}
        </span>
      )}
      {saveSlot && <div className="absolute right-1 top-1 z-10">{saveSlot}</div>}
      <div className="flex flex-1 flex-col gap-2 p-3 md:p-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-display text-xl font-bold tabular-nums md:text-2xl">{formatPrice(l.price_cad)}</span>
          <PriceBadge price={l.price_cad} reference={item.reference_price_cad} />
        </div>
        <h3 className="line-clamp-2 text-lg font-semibold">
          <Link href={`/listing/${l.item_id}`} className="after:absolute after:inset-0">
            {l.title}
          </Link>
        </h3>
        <p className="line-clamp-2 hidden text-sm text-ink-2 md:block">{firstSentence(l.description)}</p>
        <ConditionPill grade={l.condition_grade} sellerChecking={l.needs_seller_check} />
        {available && (
          <Link
            href={`/listing/${l.item_id}#reserve`}
            className="relative z-10 mt-auto hidden h-11 items-center justify-center rounded-md bg-ink font-semibold text-bg md:flex"
          >
            Reserve
          </Link>
        )}
      </div>
      <Link href={`/sale/${sale.id}`} className="relative z-10 flex items-center gap-2 border-t border-line px-4 py-2.5">
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
