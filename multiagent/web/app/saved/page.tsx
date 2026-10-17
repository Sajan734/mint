import { getGarageSales, getListings, getSellers } from "@/lib/data";
import SavedList from "./SavedList";

export const metadata = { title: "Saved | Mint" };

export default async function SavedPage() {
  const [items, sellers, sales] = await Promise.all([getListings(), getSellers(), getGarageSales()]);
  return (
    <section className="py-6">
      <h1 className="mb-4 text-[length:var(--t-2xl)] font-bold">Saved</h1>
      <SavedList items={items} sellers={sellers} sales={sales} />
    </section>
  );
}
