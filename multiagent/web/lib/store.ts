"use client";
import { useCallback, useMemo, useSyncExternalStore } from "react";
import { advanceOrder, createOrder, verifyOrder, type NewOrderInput } from "./orders";
import type { Order } from "./types";

export const KEY = "mint.v1";
export interface StoreState { saved: string[]; orders: Order[] }
export const EMPTY: StoreState = { saved: [], orders: [] };
type Store = Pick<Storage, "getItem" | "setItem">;

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
// Tiny runtime check: enough to keep the UI from crashing on bad data.
const isOrder = (v: unknown): v is Order =>
  isObj(v) && typeof v.id === "string" && typeof v.item_id === "string" &&
  typeof v.status === "string" && typeof v.total_cad === "number" &&
  (v.method === "meetup" || v.method === "shipping");

export function parseState(raw: string | null): StoreState {
  try {
    const j: unknown = raw ? JSON.parse(raw) : null;
    if (!isObj(j) || !Array.isArray(j.saved) || !Array.isArray(j.orders)) return EMPTY;
    return {
      saved: j.saved.filter((x): x is string => typeof x === "string"),
      orders: j.orders.filter(isOrder),
    };
  } catch {
    return EMPTY;
  }
}

export function readState(s: Store): StoreState {
  try { return parseState(s.getItem(KEY)); } catch { return EMPTY; }
}
export function writeState(s: Store, st: StoreState): void {
  try { s.setItem(KEY, JSON.stringify(st)); } catch { /* quota/private mode: stay in memory */ }
}

export const toggleSaved = (st: StoreState, id: string): StoreState => ({
  ...st,
  saved: st.saved.includes(id) ? st.saved.filter((x) => x !== id) : [...st.saved, id],
});
export const updateOrder = (st: StoreState, id: string, fn: (o: Order) => Order): StoreState => ({
  ...st,
  orders: st.orders.map((o) => (o.id === id ? fn(o) : o)),
});
/** Seeds first; a stored order with the same id wins. */
export function mergeOrders(seed: readonly Order[], stored: readonly Order[]): Order[] {
  const byId = new Map(stored.map((o) => [o.id, o]));
  const out = seed.map((o) => byId.get(o.id) ?? o);
  return [...out, ...stored.filter((o) => !seed.some((s) => s.id === o.id))];
}

// --- browser binding (snapshot cached by raw string so identity is stable) ---
const listeners = new Set<() => void>();
let cache: { raw: string | null; state: StoreState } = { raw: null, state: EMPTY };
const snapshot = (): StoreState => {
  let raw: string | null = null;
  try { raw = localStorage.getItem(KEY); } catch { /* blocked */ }
  if (raw !== cache.raw) cache = { raw, state: parseState(raw) };
  return cache.state;
};
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY || e.key === null) cb(); };
  window.addEventListener("storage", onStorage);
  return () => { listeners.delete(cb); window.removeEventListener("storage", onStorage); };
};
function commit(next: StoreState) {
  writeState(localStorage, next);
  cache = { raw: JSON.stringify(next), state: next };
  listeners.forEach((l) => l());
}

export function useStore() {
  const state = useSyncExternalStore(subscribe, snapshot, () => EMPTY);
  const act = (fn: (s: StoreState) => StoreState) => commit(fn(snapshot()));
  return {
    state,
    isSaved: (id: string) => state.saved.includes(id),
    toggleSaved: useCallback((id: string) => act((s) => toggleSaved(s, id)), []),
    createOrder: useCallback((i: NewOrderInput) => { const o = createOrder(i); act((s) => ({ ...s, orders: [...s.orders, o] })); return o; }, []),
    advance: useCallback((id: string) => act((s) => updateOrder(s, id, advanceOrder)), []),
    verify: useCallback((id: string) => act((s) => updateOrder(s, id, verifyOrder)), []),
  };
}

/** Seeded + stored orders. Pass the seed from the data layer. */
export function useOrders(seed: readonly Order[]): Order[] {
  const { orders } = useStore().state;
  return useMemo(() => mergeOrders(seed, orders), [seed, orders]);
}
