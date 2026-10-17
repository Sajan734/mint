import type { GarageSale, Seller } from "@/lib/types";
import { Avatar } from "./SellerCard";

const day = new Intl.DateTimeFormat("en-CA", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const hour = new Intl.DateTimeFormat("en-CA", { hour: "numeric", minute: "2-digit" });

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
  return (
    <header className="bg-surface-2 px-4 py-8 md:px-8">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-4">
        <Avatar seller={seller} size={72} />
        <div className="min-w-0">
          <h1 className="text-[length:var(--t-2xl)] font-bold md:text-[length:var(--t-3xl)]">{sale.name}</h1>
          <p className="text-ink-2">
            {day.format(new Date(sale.starts_at))} to {hour.format(new Date(sale.ends_at))} · {sale.location.neighbourhood}
          </p>
          <p className="font-mono text-sm">
            {total} items · {available} available
          </p>
        </div>
      </div>
    </header>
  );
}
