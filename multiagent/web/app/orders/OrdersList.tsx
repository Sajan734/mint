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
    <section className="mx-auto max-w-[720px] py-8 md:py-12">
      <h1 className="text-[length:var(--t-2xl)] font-bold md:text-[length:var(--t-3xl)]">Your orders</h1>
      <p className="mt-2 text-ink-2">Reservations you made on this device.</p>
      {orders.length === 0 ? (
        <div className="mt-8 rounded-lg border border-dashed border-line px-6 py-12 text-center">
          <p className="font-display text-[length:var(--t-xl)] font-bold">No orders yet.</p>
          <p className="mx-auto mt-2 max-w-[40ch] text-ink-2">Reserve something you like and follow it here, from pickup to verified.</p>
          <Link href="/" className="mt-6 inline-flex min-h-11 items-center rounded-md bg-ink px-5 font-semibold text-bg">Browse items</Link>
        </div>
      ) : (
        <ul className="mt-6 grid gap-3">
          {orders.map((o) => {
            const it = items[o.item_id];
            return (
              <li key={o.id}>
                <Link
                  href={`/orders/${o.id}`}
                  className="flex items-center gap-4 rounded-md border border-line bg-surface p-3 hover:border-ink-2 md:p-4"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {it?.thumb ? <img src={it.thumb} alt="" className="size-16 rounded-sm bg-surface-2 object-cover" /> : <span className="size-16 rounded-sm bg-surface-2" aria-hidden />}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold">{it?.title ?? "Item"}</span>
                    <span className="block text-sm text-ink-2">
                      {o.method === "meetup" ? "Meetup" : "Shipping"} · {formatPrice(o.total_cad)}
                    </span>
                  </span>
                  <span className="shrink-0 rounded-sm bg-surface-2 px-2 py-0.5 text-sm font-semibold">{STATUS_LABELS[o.status]}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
