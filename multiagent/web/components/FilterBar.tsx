"use client";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

const CATS: [string, string][] = [
  ["home_kitchen", "Home & kitchen"], ["electronics", "Electronics"], ["garden_plants", "Garden & plants"],
  ["sports_outdoors", "Sports & outdoors"], ["toys_games", "Toys & games"], ["books_media", "Books & media"],
  ["furniture", "Furniture"], ["clothing_accessories", "Clothing"],
];
const CONDS: [string, string][] = [["like_new", "Like new"], ["light_wear", "Light wear"], ["moderate_wear", "Moderate wear"], ["heavy_wear", "Heavy wear"]];
const SORTS: [string, string][] = [["newest", "Newest"], ["price_asc", "Price: low to high"], ["best_deal", "Best deal"]];
const field = "h-11 rounded-md border border-line bg-surface px-3 text-ink";

export default function FilterBar() {
  const router = useRouter();
  const path = usePathname();
  const sp = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) v ? next.set(k, v) : next.delete(k);
    const s = next.toString();
    router.replace(s ? `${path}?${s}` : path, { scroll: false });
  };
  const cat = sp.get("cat");

  return (
    <form role="search" onSubmit={(e) => { e.preventDefault(); set({ q: q.trim() || null }); }} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="min-w-48 flex-1">
          <span className="sr-only">Search items</span>
          <input
            type="search" value={q} placeholder="Search items" className={`${field} w-full`}
            onChange={(e) => {
              setQ(e.target.value);
              clearTimeout(timer.current);
              const v = e.target.value.trim();
              timer.current = setTimeout(() => set({ q: v || null }), 250);
            }}
          />
        </label>
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
        <label>
          <span className="sr-only">Sort</span>
          <select className={field} value={sp.get("sort") ?? "newest"} onChange={(e) => set({ sort: e.target.value === "newest" ? null : e.target.value })}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="flex h-11 items-center gap-2">
          <input type="checkbox" className="size-5" checked={sp.get("fair") === "1"} onChange={(e) => set({ fair: e.target.checked ? "1" : null })} />
          Fair price or better
        </label>
      </div>
      <div role="group" aria-label="Category" className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0">
        {[["", "All"], ...CATS].map(([v, l]) => (
          <button
            key={v} type="button" aria-pressed={(cat ?? "") === v} onClick={() => set({ cat: v || null })}
            className={`h-11 shrink-0 snap-start rounded-full border px-4 ${(cat ?? "") === v ? "border-ink bg-ink text-bg" : "border-line bg-surface"}`}
          >
            {l}
          </button>
        ))}
      </div>
    </form>
  );
}
