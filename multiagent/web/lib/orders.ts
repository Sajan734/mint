import type { FulfilmentMethod, Order, OrderStatus } from "./types";

export const MEETUP_FLOW: readonly OrderStatus[] = ["reserved", "confirmed", "picked_up", "verified"];
export const SHIPPING_FLOW: readonly OrderStatus[] = ["reserved", "paid", "shipped", "delivered", "verified"];

export const flowFor = (method: FulfilmentMethod): readonly OrderStatus[] =>
  method === "meetup" ? MEETUP_FLOW : SHIPPING_FLOW;

export const STATUS_LABELS: Record<OrderStatus, string> = {
  reserved: "Reserved",
  confirmed: "Confirmed",
  picked_up: "Picked up",
  paid: "Paid",
  shipped: "Shipped",
  delivered: "Delivered",
  verified: "Verified",
};

export interface NewOrderInput {
  id: string;
  item_id: string;
  created_at: string;
  method: FulfilmentMethod;
  pickup_slot?: string;
  ship_to?: Order["ship_to"];
  price_cad: number;
  shipping_cad?: number;
  comparison_id?: string;
}

export function createOrder(input: NewOrderInput): Order {
  const shipping_cad = input.method === "shipping" ? (input.shipping_cad ?? 0) : 0;
  return { ...input, shipping_cad, total_cad: input.price_cad + shipping_cad, status: "reserved" };
}

/** Next status in the flow, or null when finished. "verified" is reached via verifyOrder, not advance. */
export function nextStatus(method: FulfilmentMethod, status: OrderStatus): OrderStatus | null {
  const flow = flowFor(method);
  const next = flow[flow.indexOf(status) + 1];
  return next === undefined || next === "verified" ? null : next;
}

export function advanceOrder(order: Order): Order {
  const next = nextStatus(order.method, order.status);
  return next ? { ...order, status: next } : order;
}

/** Verify is available once the item is in hand (picked_up / delivered). */
export const canVerify = (order: Order): boolean =>
  order.status === (order.method === "meetup" ? "picked_up" : "delivered");

export function verifyOrder(order: Order): Order {
  return canVerify(order) ? { ...order, status: "verified" } : order;
}

export interface TimelineStep {
  status: OrderStatus;
  label: string;
  state: "done" | "current" | "upcoming";
}

export function timelineFor(method: FulfilmentMethod, status: OrderStatus): TimelineStep[] {
  const flow = flowFor(method);
  const at = flow.indexOf(status);
  return flow.map((s, i) => ({
    status: s,
    label: STATUS_LABELS[s],
    state: i < at || status === "verified" ? "done" : i === at ? "current" : "upcoming",
  }));
}
