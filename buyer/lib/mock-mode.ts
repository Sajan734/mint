// Twin: seller/lib/mock-mode.ts (keep identical)
"use client";
// Demo switch shared by both apps. "?mock=1" / "?mock=0" on any page sets localStorage "mint.mock"; it then stays
// until turned off. Both headers show a "Demo data" pill while it is on.
import { useSyncExternalStore } from "react";

export const MOCK_KEY = "mint.mock";
export const DEMO_SELLER_ID = "sel_raj";

function stored(): boolean {
  try {
    return localStorage.getItem(MOCK_KEY) === "1";
  } catch {
    return false;
  }
}
function write(on: boolean): void {
  try {
    localStorage.setItem(MOCK_KEY, on ? "1" : "0");
  } catch {
    /* blocked: the switch just will not stick */
  }
}
// A ?mock param in the URL wins and is remembered. Idempotent and silent, so it is safe inside a snapshot read.
function syncFromUrl(): void {
  const v = new URLSearchParams(window.location.search).get("mock");
  if (v === "1" || v === "0") write(v === "1");
}

export function isMockMode(): boolean {
  if (typeof window === "undefined") return false;
  syncFromUrl();
  return stored();
}

const listeners = new Set<() => void>();
export function setMockMode(on: boolean): void {
  if (typeof window === "undefined") return;
  // Drop a leftover ?mock param first, or it would turn the switch straight back on.
  const url = new URL(window.location.href);
  if (url.searchParams.has("mock")) {
    url.searchParams.delete("mock");
    window.history.replaceState(window.history.state, "", url);
  }
  write(on);
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === MOCK_KEY || e.key === null) cb();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export const useMockMode = (): boolean => useSyncExternalStore(subscribe, isMockMode, () => false);
