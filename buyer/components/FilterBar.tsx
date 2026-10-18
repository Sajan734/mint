"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

const CATS: [string, string][] = [
  ["home_kitchen", "Home & kitchen"], ["electronics", "Electronics"], ["garden_plants", "Garden & plants"],
  ["sports_outdoors", "Sports & outdoors"], ["toys_games", "Toys & games"], ["books_media", "Books & media"],
  ["furniture", "Furniture"], ["clothing_accessories", "Clothing"],
];
const CONDS: [string, string][] = [["like_new", "Like new"], ["light_wear", "Light wear"], ["moderate_wear", "Moderate wear"], ["heavy_wear", "Heavy wear"]];
const SORTS: [string, string][] = [["newest", "Newest"], ["price_asc", "Price: low to high"], ["best_deal", "Best deal"]];
const field = "field h-11 rounded-full px-4 text-[15px]";

export default function FilterBar() {
  const router = useRouter();
  const path = usePathname();
  const sp = useSearchParams();

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    const s = next.toString();
    router.replace(s ? `${path}?${s}` : path, { scroll: false });
  };
  const cat = sp.get("cat");

  return (
    <form role="group" aria-label="Filters" onSubmit={(e) => e.preventDefault()} className="flex flex-col gap-3">
      <div className="grid grid-cols-2 items-center gap-2 md:flex md:flex-wrap md:gap-3 [&_select]:md:w-auto">
        <label>
          <span className="sr-only">Condition</span>
          <select className={field} value={sp.get("cond") ?? ""} onChange={(e) => set({ cond: e.target.value || null })}>
            <option value="">Any condition</option>
            {CONDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label>
          <span className="sr-only">Delivery</span>
          <select className={field} value={sp.get("delivery") ?? ""} onChange={(e) => set({ delivery: e.target.value || null })}>
            <option value="">Pickup or shipping</option>
            <option value="shipping">Ships</option>
          </select>
        </label>
        <label className="col-span-2 md:col-span-1">
          <span className="sr-only">Sort</span>
          <select className={field} value={sp.get("sort") ?? "newest"} onChange={(e) => set({ sort: e.target.value === "newest" ? null : e.target.value })}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="col-span-2 flex h-11 items-center gap-2 text-sm md:col-span-1">
          <input type="checkbox" className="size-5 accent-[var(--leaf)]" checked={sp.get("fair") === "1"} onChange={(e) => set({ fair: e.target.checked ? "1" : null })} />
          Fair price or better
        </label>
      </div>
      <div role="group" aria-label="Category" className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:flex-wrap md:overflow-visible md:px-0">
        {[["", "All"], ...CATS].map(([v, l]) => (
          <button
            key={v} type="button" aria-pressed={(cat ?? "") === v} onClick={() => set({ cat: v || null })}
            className={`h-11 shrink-0 snap-start rounded-full px-4 text-[15px] font-medium transition-colors active:scale-[0.97] ${(cat ?? "") === v ? "bg-pine text-on-pine" : "bg-surface hover:bg-surface-2"}`}
          >
            {l}
          </button>
        ))}
      </div>
    </form>
  );
}
