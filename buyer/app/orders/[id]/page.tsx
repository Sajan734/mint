import { getOrders, getVerifySample } from "@/lib/data";
import { itemInfoMap } from "../items";
import OrderDetail from "./OrderDetail";

export const metadata = { title: "Order · Mint" };

export default async function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [seed, items, sample] = await Promise.all([getOrders(), itemInfoMap(), getVerifySample()]);
  return <OrderDetail id={id} seed={seed} items={items} explanation={sample.explanation} />;
}
