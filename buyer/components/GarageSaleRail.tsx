import Link from "next/link";
import type { GarageSale, Seller } from "@/lib/types";

export interface SaleTile {
  sale: GarageSale;
  seller: Seller;
  cover: string; // first frame URL
  itemCount: number;
}

const TZ = "America/Toronto";
const day = new Intl.DateTimeFormat("en-CA", { weekday: "short", timeZone: TZ });
const date = new Intl.DateTimeFormat("en-CA", { day: "numeric", timeZone: TZ });
const month = new Intl.DateTimeFormat("en-CA", { month: "short", timeZone: TZ });
const time = new Intl.DateTimeFormat("en-CA", { hour: "numeric", minute: "2-digit", timeZone: TZ });

// The neighbourhood noticeboard: one line per sale, the date set large like a hand-lettered sign, then what and where.
export default function GarageSaleRail({ tiles }: { tiles: SaleTile[] }) {
  return (
    <ul aria-label="Garage sales" className="flex list-none flex-col gap-2 p-0">
      {tiles.map(({ sale, seller, cover, itemCount }) => {
        const start = new Date(sale.starts_at);
        return (
          <li key={sale.id}>
            <Link
              href={`/sale/${sale.id}`}
              className="group grid grid-cols-[4.5rem_1fr] items-center gap-x-4 gap-y-2 rounded-[20px] bg-surface p-3 pr-4 transition-colors hover:bg-surface-2 sm:grid-cols-[5.5rem_1fr_auto] sm:gap-x-6 sm:p-4"
            >
              <span className="flex flex-col items-center rounded-[14px] bg-raised py-2 text-center leading-none">
                <span className="text-sm font-semibold text-ink-2">{day.format(start)}</span>
                <span className="font-display text-[2rem] leading-[1.05]">{date.format(start)}</span>
                <span className="text-sm font-semibold text-leaf">{month.format(start)}</span>
              </span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-lg font-semibold leading-snug group-hover:underline group-hover:underline-offset-4">
                  {sale.name}
                </span>
                <span className="text-ink-2">
                  {seller.name} in {sale.location.neighbourhood} · {time.format(start)} to {time.format(new Date(sale.ends_at))}
                </span>
              </span>
              <span className="col-start-2 flex items-center gap-3 sm:col-start-3">
                {/* The sale's first item: a glance at what is there. Phones skip it to keep the row short. */}
                {/* eslint-disable-next-line @next/next/no-img-element -- scan frames from /public or storage */}
                <img src={cover} alt="" className="hidden size-14 shrink-0 rounded-[12px] bg-raised object-contain p-1 sm:block" />
                <span className="whitespace-nowrap text-sm font-semibold tabular-nums">
                  {itemCount} {itemCount === 1 ? "item" : "items"}
                  {sale.ships && <span className="block font-medium text-ink-2">Ships too</span>}
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
