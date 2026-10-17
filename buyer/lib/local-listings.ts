// Twin: seller/lib/local-listings.ts (keep identical)
"use client";
// Drafts and published listings made on this device. Both apps read and write the same browser key, so a listing
// published in /sell shows on the landing page. Never touch "mint.v1": buyer/lib/store.ts owns it and drops extra fields.
import { useSyncExternalStore } from "react";
import type { MarketListing } from "./types";

export const LOCAL_KEY = "mint.listings.v1";
export type LocalState = "draft" | "published";
export interface LocalListing {
  id: string;
  state: LocalState;
  source: "mock" | "live";
  suggested_price_cad: number;
  market: MarketListing;
  created_at: string;
  updated_at: string;
  published_at?: string;
}

const EMPTY: readonly LocalListing[] = Object.freeze([]);
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
// Light check: enough to keep a corrupt or hand-edited entry from crashing a page.
const isLocal = (v: unknown): v is LocalListing =>
  isObj(v) &&
  typeof v.id === "string" &&
  (v.state === "draft" || v.state === "published") &&
  (v.source === "mock" || v.source === "live") &&
  typeof v.suggested_price_cad === "number" &&
  typeof v.created_at === "string" &&
  typeof v.updated_at === "string" &&
  isObj(v.market) &&
  isObj(v.market.listing);

export function parseListings(raw: string | null): LocalListing[] {
  try {
    const j: unknown = raw ? JSON.parse(raw) : null;
    return Array.isArray(j) ? j.filter(isLocal) : [];
  } catch {
    return [];
  }
}

// Snapshot cached by raw string, so useSyncExternalStore sees the same array until storage really changes.
let cache: { raw: string | null; list: readonly LocalListing[] } = { raw: null, list: EMPTY };
function snapshot(): readonly LocalListing[] {
  if (typeof window === "undefined") return EMPTY;
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(LOCAL_KEY);
  } catch {
    /* blocked */
  }
  if (raw !== cache.raw) cache = { raw, list: raw ? parseListings(raw) : EMPTY };
  return cache.list;
}

const listeners = new Set<() => void>();
function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === LOCAL_KEY || e.key === null) cb();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export const listLocal = (): LocalListing[] => [...snapshot()];
export const getLocal = (id: string): LocalListing | null => snapshot().find((l) => l.id === id) ?? null;

/** Add, or replace the entry with the same id in place. */
export function upsertLocal(e: LocalListing): void {
  if (typeof window === "undefined") return;
  const cur = snapshot();
  const list = cur.some((l) => l.id === e.id) ? cur.map((l) => (l.id === e.id ? e : l)) : [...cur, e];
  const raw = JSON.stringify(list);
  try {
    localStorage.setItem(LOCAL_KEY, raw);
  } catch {
    /* quota or private mode: nothing is saved. ponytail: no in-memory fallback; add one if publish must work offline */
    return;
  }
  cache = { raw, list };
  // The "storage" event does not fire in the tab that wrote, so tell this tab's listeners ourselves.
  listeners.forEach((l) => l());
}

export const useLocalListings = (): LocalListing[] =>
  useSyncExternalStore(subscribe, snapshot, () => EMPTY) as LocalListing[];
