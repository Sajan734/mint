import { getGarageSales, getListings, getSellers } from "@/lib/data";
import SavedList from "./SavedList";

export const metadata = { title: "Saved | Mint" };

export default async function SavedPage() {
  const [items, sellers, sales] = await Promise.all([getListings(), getSellers(), getGarageSales()]);
  return (
    <section className="py-8 md:py-12">
      <h1 className="text-[length:var(--t-2xl)] font-bold md:text-[length:var(--t-3xl)]">Saved</h1>
      <p className="mb-8 mt-2 text-ink-2">Things you liked, kept on this device.</p>
      <SavedList items={items} sellers={sellers} sales={sales} />
    </section>
  );
}
