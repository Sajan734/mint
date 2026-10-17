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
      <section className="py-8">
        <h1 className="text-[length:var(--t-2xl)] font-bold">We could not find that order.</h1>
        <p className="mt-3 text-ink-2">It may have been cleared from this browser.</p>
        <Link href="/orders" className="mt-6 inline-flex min-h-11 items-center rounded-md bg-ink px-5 text-bg">Back to orders</Link>
      </section>
    );
  }

  const item = items[order.item_id];
  const canAdvance = nextStatus(order.method, order.status) !== null;
  return (
    <section className="grid gap-6 py-8">
      <Link href="/orders" className="text-sm text-ink-2 underline">All orders</Link>
      <h1 className="text-[length:var(--t-2xl)] font-bold">{item?.title ?? "Your order"}</h1>
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
        <dt className="text-ink-2">Method</dt><dd>{order.method === "meetup" ? "Meetup" : "Shipping"}</dd>
        {order.pickup_slot && (<><dt className="text-ink-2">Pickup slot</dt><dd>{new Date(order.pickup_slot).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}</dd></>)}
        {order.ship_to && (<><dt className="text-ink-2">Ship to</dt><dd>{order.ship_to.city}</dd></>)}
        <dt className="text-ink-2">Item</dt><dd>{formatPrice(order.price_cad)}</dd>
        <dt className="text-ink-2">Shipping</dt><dd>{formatPrice(order.shipping_cad)}</dd>
        <dt className="font-semibold">Total</dt><dd className="font-semibold">{formatPrice(order.total_cad)}</dd>
      </dl>
      <OrderTimeline method={order.method} status={order.status} />
      {canAdvance && (
        <button type="button" onClick={() => advance(order.id)} className="min-h-11 w-fit rounded-md border border-line px-5 hover:border-ink-2">
          Advance (demo)
        </button>
      )}
      {(canVerify(order) || order.status === "verified") && (
        <VerifyItemPanel explanation={explanation} verified={order.status === "verified"} onVerify={() => verify(order.id)} />
      )}
    </section>
  );
}
