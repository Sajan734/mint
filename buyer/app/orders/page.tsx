import { getOrders } from "@/lib/data";
import { itemInfoMap } from "./items";
import OrdersList from "./OrdersList";

export const metadata = { title: "Your orders · Mint" };

export default async function OrdersPage() {
  const [seed, items] = await Promise.all([getOrders(), itemInfoMap()]);
  return <OrdersList seed={seed} items={items} />;
}
