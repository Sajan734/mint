// Server-side accessors. Async so a later swap to fetch(MINT_API_URL) changes only this file.
import type { CompareResult, GarageSale, MarketListing, Order, Seller } from "../types";
import { garageSales, listings, orders, sellers, verifySample, frameFallbacks } from "./mock";
import { applyQuery, type ListingQuery } from "./query";

const shipsBySale = Object.fromEntries(garageSales.map((s) => [s.id, s.ships]));

export async function getListings(q?: ListingQuery): Promise<MarketListing[]> {
  return applyQuery(listings, q, shipsBySale);
}
export async function getListing(id: string): Promise<MarketListing | null> {
  return listings.find((m) => m.listing.item_id === id) ?? null;
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
