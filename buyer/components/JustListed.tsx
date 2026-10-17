"use client";
// "Just listed": listings published in this browser (lib/local-listings), newest first. Hidden when there are none.
// Rail is the horizontal row every landing shelf uses.
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

export function Rail({ id, title, action, children }: { id: string; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id={id} className="text-[length:var(--t-xl)] font-bold tracking-tight">{title}</h2>
        {action}
      </div>
      <ul
        aria-labelledby={id}
        className="-mx-4 flex list-none snap-x gap-3 overflow-x-auto scroll-px-4 px-4 pb-2 md:-mx-6 md:gap-4 md:scroll-px-6 md:px-6 lg:mx-0 lg:scroll-px-0 lg:px-0"
      >
        {Children.toArray(children).map((c, i) => (
          <li key={isValidElement(c) ? c.key : i} className="w-40 shrink-0 snap-start sm:w-48 lg:w-52">
            {c}
          </li>
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
    <Rail id="just-h" title="Just listed">
      {cards}
    </Rail>
  );
}
