import { getListings } from "@/lib/data";

export interface ItemInfo { title: string; thumb: string | null }

export async function itemInfoMap(): Promise<Record<string, ItemInfo>> {
  const all = await getListings();
  return Object.fromEntries(all.map((m) => [m.listing.item_id, { title: m.listing.title, thumb: m.frames[0] ?? null }]));
}
