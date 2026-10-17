// Server-side accessors. Async so a later swap to fetch(MINT_API_URL) changes only this file.
import type { CompareResult, GarageSale, MarketListing, Order, Seller } from "../types";
import { garageSales, listings, orders, sellers, verifySample, frameFallbacks } from "./mock";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { applyQuery, type ListingQuery } from "./query";

/** Real hero frames live in gitignored public/local; fall back to procedural frames when absent. */
const withFrames = (m: MarketListing): MarketListing => {
  const first = m.frames[0];
  const fb = frameFallbacks[m.listing.item_id];
  return fb && first?.startsWith("/local/") && !existsSync(join(process.cwd(), "public", first)) ? { ...m, frames: fb } : m;
};

const shipsBySale = Object.fromEntries(garageSales.map((s) => [s.id, s.ships]));

export async function getListings(q?: ListingQuery): Promise<MarketListing[]> {
  return applyQuery(listings, q, shipsBySale).map(withFrames);
}
export async function getListing(id: string): Promise<MarketListing | null> {
  const m = listings.find((x) => x.listing.item_id === id);
  return m ? withFrames(m) : null;
}
export async function getGarageSales(): Promise<GarageSale[]> {
  return garageSales;
}
export async function getGarageSale(id: string): Promise<GarageSale | null> {
  return garageSales.find((s) => s.id === id) ?? null;
}
export async function getSellers(): Promise<Seller[]> {
  return sellers;
}
export async function getSeller(id: string): Promise<Seller | null> {
  return sellers.find((s) => s.id === id) ?? null;
}
export async function getOrders(): Promise<Order[]> {
  return orders;
}
export async function getVerifySample(): Promise<CompareResult> {
  return verifySample;
}
export async function getFrameFallback(itemId: string): Promise<string[] | null> {
  return frameFallbacks[itemId] ?? null;
}
