"use client";
// "Just listed": listings published in this browser (lib/local-listings), newest first. Hidden when there are none.
// Rail is the grid every landing shelf uses (a wrapping grid, not a side-scrolling row: docs/design/DESIGN.md §5).
import { Children, isValidElement, type ReactNode } from "react";
import type { GarageSale, Seller } from "@/lib/types";
import { useLocalListings, type LocalListing } from "@/lib/local-listings";
import ListingCard from "./ListingCard";
import SaveButton from "./SaveButton";

export const JUST_LISTED_MAX = 8;

/** Published entries only, newest publish first, at most `max`. */
export function justListed(all: readonly LocalListing[], max = JUST_LISTED_MAX): LocalListing[] {
  const when = (e: LocalListing) => e.published_at ?? e.updated_at;
  return all
    .filter((e) => e.state === "published")
    .sort((a, b) => when(b).localeCompare(when(a)))
    .slice(0, max);
}

export function Rail({ id, title, note, action, children }: { id: string; title: string; note?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="rise flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="flex max-w-2xl flex-col gap-2">
          <h2 id={id} className="text-[length:var(--t-xl)] md:text-[length:var(--t-2xl)]">{title}</h2>
          {note && <p className="text-ink-2">{note}</p>}
        </div>
        {action}
      </div>
      <ul aria-labelledby={id} className="grid list-none grid-cols-2 gap-x-3 gap-y-8 p-0 sm:grid-cols-3 sm:gap-x-5 lg:grid-cols-4 lg:gap-x-6">
        {Children.toArray(children).map((c, i) => (
          <li key={isValidElement(c) ? c.key : i}>{c}</li>
        ))}
      </ul>
    </section>
  );
}

export default function JustListed({ sellers, sales }: { sellers: Seller[]; sales: GarageSale[] }) {
  const cards = justListed(useLocalListings()).flatMap((e) => {
    const seller = sellers.find((s) => s.id === e.market.seller_id);
    const sale = sales.find((s) => s.id === e.market.garage_sale_id);
    if (!seller || !sale) return [];
    const item = { ...e.market, listing: { ...e.market.listing, item_id: e.id } };
    return [
      <ListingCard
        key={e.id}
        item={item}
        seller={seller}
        sale={sale}
        saveSlot={<SaveButton itemId={e.id} title={item.listing.title} />}
      />,
    ];
  });
  if (!cards.length) return null;
  return (
    <Rail id="just-h" title="Just listed" note="Published from this browser.">
      {cards}
    </Rail>
  );
}
