import Link from "next/link";
import type { GarageSale, Seller } from "@/lib/types";

export interface SaleTile {
  sale: GarageSale;
  seller: Seller;
  cover: string; // first frame URL
  itemCount: number;
}

const fmt = new Intl.DateTimeFormat("en-CA", { weekday: "short", hour: "numeric", minute: "2-digit" });

// A sale sign: object on the pad, a perforated tear line with two notches, then the details.
export default function GarageSaleRail({ tiles }: { tiles: SaleTile[] }) {
  return (
    <ul
      aria-label="Garage sales"
      className="-mx-4 flex list-none snap-x snap-mandatory gap-4 overflow-x-auto scroll-px-4 px-4 pb-3 pt-1 md:-mx-6 md:scroll-px-6 md:px-6 lg:mx-0 lg:scroll-px-0 lg:px-0"
    >
      {tiles.map(({ sale, seller, cover, itemCount }) => (
        <li key={sale.id} className="w-64 shrink-0 snap-start">
          <Link
            href={`/sale/${sale.id}`}
            className="group relative block rounded-lg border border-line-strong bg-surface transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-ink hover:shadow-[var(--shadow-hover)] motion-reduce:hover:translate-y-0"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={cover} alt="" className="pad aspect-[4/3] w-full rounded-t-[calc(var(--r-lg)-1px)] object-contain p-3" />
            <span aria-hidden className="relative block border-t-2 border-dashed border-line-strong">
              <span className="absolute -left-[11px] -top-2.5 size-5 rounded-full border border-line-strong bg-bg [clip-path:inset(0_0_0_50%)]" />
              <span className="absolute -right-[11px] -top-2.5 size-5 rounded-full border border-line-strong bg-bg [clip-path:inset(0_50%_0_0)]" />
            </span>
            <span className="block p-4 pt-3">
              <span className="block truncate font-display text-lg font-bold leading-tight">{sale.name}</span>
              <span className="block truncate text-sm text-ink-2">
                {seller.name} · {sale.location.neighbourhood}
              </span>
              <span className="mt-3 flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs text-ink-2">
                  {fmt.format(new Date(sale.starts_at))} to {fmt.format(new Date(sale.ends_at))}
                </span>
                <span className="shrink-0 rounded-full bg-mint-wash px-2 py-0.5 font-mono text-xs text-mint-ink">{itemCount} items</span>
              </span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
