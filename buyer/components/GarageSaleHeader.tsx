import type { GarageSale, Seller } from "@/lib/types";
import { Avatar } from "./SellerCard";

const TZ = "America/Toronto";
const weekday = new Intl.DateTimeFormat("en-CA", { weekday: "short", timeZone: TZ });
const date = new Intl.DateTimeFormat("en-CA", { day: "numeric", timeZone: TZ });
const month = new Intl.DateTimeFormat("en-CA", { month: "short", timeZone: TZ });
const hour = new Intl.DateTimeFormat("en-CA", { hour: "numeric", minute: "2-digit", timeZone: TZ });

export default function GarageSaleHeader({
  sale,
  seller,
  total,
  available,
}: {
  sale: GarageSale;
  seller: Seller;
  total: number;
  available: number;
}) {
  const start = new Date(sale.starts_at);
  // The sale's sign: the same hand-lettered date block as the landing's noticeboard (GarageSaleRail).
  return (
    <header className="grid gap-6 rounded-[28px] bg-surface p-5 sm:grid-cols-[7rem_1fr] sm:items-center sm:gap-8 sm:p-8 md:p-10">
      <span className="flex w-24 flex-col items-center rounded-[18px] bg-raised py-3 text-center leading-none sm:w-28">
        <span className="font-semibold text-ink-2">{weekday.format(start)}</span>
        <span className="font-display text-[3rem] leading-[1.05]">{date.format(start)}</span>
        <span className="font-semibold text-leaf">{month.format(start)}</span>
      </span>
      <div className="flex min-w-0 flex-col gap-3">
        <h1 className="text-[2.25rem] md:text-[3.25rem]">{sale.name}</h1>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[length:var(--t-lg)] text-ink-2">
          <Avatar seller={seller} size={32} />
          <span>
            {seller.name} in {sale.location.neighbourhood} · {hour.format(start)} to {hour.format(new Date(sale.ends_at))}
          </span>
        </p>
        <p className="text-[15px] font-semibold tabular-nums">
          {total} items · {available} available
        </p>
      </div>
    </header>
  );
}
