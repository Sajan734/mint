import Link from "next/link";
import type { GarageSale, Seller } from "@/lib/types";

export interface SaleTile {
  sale: GarageSale;
  seller: Seller;
  cover: string; // first frame URL
  itemCount: number;
}

const fmt = new Intl.DateTimeFormat("en-CA", { weekday: "short", hour: "numeric", minute: "2-digit" });

export default function GarageSaleRail({ tiles }: { tiles: SaleTile[] }) {
  return (
    <ul aria-label="Garage sales" className="flex list-none snap-x gap-4 overflow-x-auto p-0">
      {tiles.map(({ sale, seller, cover, itemCount }) => (
        <li key={sale.id} className="w-60 shrink-0 snap-start">
          <Link href={`/sale/${sale.id}`} className="block overflow-hidden rounded-md border border-line bg-surface hover:border-ink-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={cover} alt="" className="aspect-square w-full bg-surface-2 object-contain" />
            <span className="block p-3">
              <span className="block truncate font-semibold">{sale.name}</span>
              <span className="block truncate text-sm text-ink-2">{seller.name}</span>
              <span className="block font-mono text-xs text-ink-2">
                {itemCount} items · {fmt.format(new Date(sale.starts_at))} to {fmt.format(new Date(sale.ends_at))}
              </span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
