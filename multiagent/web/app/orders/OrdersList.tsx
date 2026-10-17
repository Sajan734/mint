"use client";
import Link from "next/link";
import { useOrders } from "@/lib/store";
import { STATUS_LABELS } from "@/lib/orders";
import { formatPrice } from "@/lib/format";
import type { Order } from "@/lib/types";
import type { ItemInfo } from "./items";

export default function OrdersList({ seed, items }: { seed: Order[]; items: Record<string, ItemInfo> }) {
  const orders = useOrders(seed);
  return (
    <section className="py-8">
      <h1 className="text-[length:var(--t-2xl)] font-bold">Your orders</h1>
      {orders.length === 0 ? (
        <p className="mt-4 text-ink-2">
          No orders yet. <Link href="/" className="underline">Browse items</Link> and reserve one to see it here.
        </p>
      ) : (
        <ul className="mt-6 grid gap-3">
          {orders.map((o) => {
            const it = items[o.item_id];
            return (
              <li key={o.id}>
                <Link
                  href={`/orders/${o.id}`}
                  className="flex items-center gap-4 rounded-md border border-line bg-surface p-3 hover:border-ink-2"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {it?.thumb ? <img src={it.thumb} alt="" className="size-16 rounded-sm object-cover" /> : <span className="size-16 rounded-sm bg-surface-2" aria-hidden />}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold">{it?.title ?? "Item"}</span>
                    <span className="block text-sm text-ink-2">
                      {o.method === "meetup" ? "Meetup" : "Shipping"} · {formatPrice(o.total_cad)}
                    </span>
                  </span>
                  <span className="rounded-sm bg-surface-2 px-2 py-0.5 text-sm">{STATUS_LABELS[o.status]}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
