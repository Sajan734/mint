import Link from "next/link";
import type { GarageSale, Seller } from "@/lib/types";

export function Avatar({ seller, size = 32 }: { seller: Seller; size?: number }) {
  return (
    <span
      aria-hidden
      style={{ width: size, height: size }}
      className="grid shrink-0 place-items-center rounded-full bg-mint-wash font-semibold text-mint-ink"
    >
      {seller.name.slice(0, 1).toUpperCase()}
    </span>
  );
}

export default function SellerCard({
  seller,
  sale,
  size = "md",
}: {
  seller: Seller;
  sale?: GarageSale;
  size?: "sm" | "md";
}) {
  return (
    <section aria-label={`Seller ${seller.name}`} className="flex items-center gap-3 rounded-md bg-surface p-4">
      <Avatar seller={seller} size={size === "sm" ? 32 : 48} />
      <div className="min-w-0">
        <Link href={`/seller/${seller.id}`} className="font-semibold hover:underline">
          {seller.name}
        </Link>
        <p className="text-sm text-ink-2">
          {seller.neighbourhood} · {seller.rating.toFixed(1)} ({seller.rating_count})
        </p>
        {size === "md" && <p className="text-sm text-ink-2">{seller.response_time}</p>}
        {sale && (
          <Link href={`/sale/${sale.id}`} className="text-sm text-mint-ink hover:underline">
            {sale.name}
          </Link>
        )}
      </div>
    </section>
  );
}
