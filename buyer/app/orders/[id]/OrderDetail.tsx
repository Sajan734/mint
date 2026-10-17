"use client";
import Link from "next/link";
import OrderTimeline from "@/components/OrderTimeline";
import VerifyItemPanel from "@/components/VerifyItemPanel";
import { useOrders, useStore } from "@/lib/store";
import { canVerify, nextStatus } from "@/lib/orders";
import { formatPrice } from "@/lib/format";
import type { Explanation, Order } from "@/lib/types";
import type { ItemInfo } from "../items";

interface Props { id: string; seed: Order[]; items: Record<string, ItemInfo>; explanation: Explanation | null }

export default function OrderDetail({ id, seed, items, explanation }: Props) {
  const order = useOrders(seed).find((o) => o.id === id);
  const { advance, verify } = useStore();

  if (!order) {
    return (
      <section className="mx-auto max-w-[720px] py-12">
        <h1 className="text-[length:var(--t-2xl)] font-bold">We could not find that order.</h1>
        <p className="mt-3 text-ink-2">It may have been cleared from this browser.</p>
        <Link href="/orders" className="mt-6 inline-flex min-h-11 items-center rounded-md bg-ink px-5 text-bg">Back to orders</Link>
      </section>
    );
  }

  const item = items[order.item_id];
  const canAdvance = nextStatus(order.method, order.status) !== null;
  return (
    <section className="mx-auto grid max-w-[720px] gap-8 py-8 md:py-12">
      <header className="grid gap-3">
        <Link href="/orders" className="inline-flex min-h-11 w-fit items-center gap-1 text-sm text-ink-2 hover:text-ink">
          <svg aria-hidden viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m15 6-6 6 6 6" /></svg>
          All orders
        </Link>
        <div className="flex items-center gap-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {item?.thumb && <img src={item.thumb} alt="" className="size-20 shrink-0 rounded-md bg-surface-2 object-cover" />}
          <h1 className="text-balance text-[length:var(--t-2xl)] font-bold">{item?.title ?? "Your order"}</h1>
        </div>
      </header>
      <div className="grid gap-8 md:grid-cols-2">
        <section aria-labelledby="progress-h" className="grid content-start gap-4">
          <h2 id="progress-h" className="text-[length:var(--t-lg)] font-bold">Progress</h2>
          <OrderTimeline method={order.method} status={order.status} />
          {canAdvance && (
            <button type="button" onClick={() => advance(order.id)} className="min-h-11 w-fit rounded-md border border-dashed border-line px-5 text-ink-2 hover:border-ink-2 hover:text-ink">
              Advance (demo)
            </button>
          )}
        </section>
        <section aria-labelledby="details-h" className="grid content-start gap-4">
          <h2 id="details-h" className="text-[length:var(--t-lg)] font-bold">Details</h2>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 rounded-md bg-surface p-4 text-sm">
            <dt className="text-ink-2">Method</dt><dd>{order.method === "meetup" ? "Meet in person" : "Shipping"}</dd>
            {order.pickup_slot && (<><dt className="text-ink-2">Pickup slot</dt><dd>{new Date(order.pickup_slot).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}</dd></>)}
            {order.ship_to && (<><dt className="text-ink-2">Ship to</dt><dd>{order.ship_to.city}</dd></>)}
            <dt className="text-ink-2">Item</dt><dd className="tabular-nums">{formatPrice(order.price_cad)}</dd>
            <dt className="text-ink-2">Shipping</dt><dd className="tabular-nums">{formatPrice(order.shipping_cad)}</dd>
            <dt className=" pt-2 font-semibold">Total</dt><dd className=" pt-2 font-semibold tabular-nums">{formatPrice(order.total_cad)}</dd>
          </dl>
        </section>
      </div>
      {(canVerify(order) || order.status === "verified") && (
        <VerifyItemPanel explanation={explanation} verified={order.status === "verified"} onVerify={() => verify(order.id)} />
      )}
    </section>
  );
}
