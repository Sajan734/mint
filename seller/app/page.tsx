"use client";
import { NEW_SCAN_HREF } from "@/lib/scan";
import ListingRow, { buildRows, countByStatus, STATUS_WORD, type RowStatus } from "@/components/ListingRow";
import { useLocalListings } from "@/lib/local-listings";
import { useMockMode } from "@/lib/mock-mode";
import type { MarketListing } from "@/lib/types";
import myListings from "@/mock/my-listings.json";
import realScans from "@/mock/real-scans.json";

// The demo person (buyer/mock/sellers.json sel_raj; tests/dashboard.test.tsx checks the two agree).
const SELLER_LINE = "Raj S. · Agincourt";
const DEMO = myListings as unknown as MarketListing[];
const CHIPS: [RowStatus, string][] = [["draft", "Drafts"], ["available", "Listed"], ["reserved", "Reserved"], ["sold", "Sold"]];

interface RealScan { id: string; name: string; note?: string; images: string[] }

/** Your listings: this device's drafts and listings, plus Raj's demo listings and real scans in demo mode. */
export default function Dashboard() {
  const mock = useMockMode();
  const local = useLocalListings();
  const rows = buildRows(local, mock ? DEMO : []);
  const counts = countByStatus(rows);
  const scans = mock ? (realScans as RealScan[]) : [];

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-[length:var(--t-2xl)] font-bold">Your listings</h1>
          <p className="text-ink-2">{SELLER_LINE}</p>
        </div>
        {rows.length > 0 && (
          <a href={NEW_SCAN_HREF} className="btn-primary">
            New listing
          </a>
        )}
      </header>

      {rows.length === 0 ? (
        <section className="flex flex-col items-start gap-4 rounded-lg border border-line bg-surface p-6">
          <p className="text-[length:var(--t-lg)]">Nothing listed yet. Scan something to sell it.</p>
          <a href={NEW_SCAN_HREF} className="btn-primary">
            New listing
          </a>
        </section>
      ) : (
        <section aria-labelledby="mine" className="flex flex-col gap-3">
          <h2 id="mine" className="sr-only">
            Listings
          </h2>
          <ul aria-label="Listing counts" className="flex flex-wrap gap-2">
            {CHIPS.filter(([s]) => counts[s] > 0).map(([s, word]) => (
              <li key={s} className="rounded-full border border-line bg-surface px-3 py-1 text-sm font-semibold">
                {counts[s]} {counts[s] === 1 ? STATUS_WORD[s] : word}
              </li>
            ))}
          </ul>
          <ul className="divide-y divide-line border-y border-line">
            {rows.map((r) => (
              <ListingRow key={r.id} row={r} />
            ))}
          </ul>
        </section>
      )}

      {scans.length > 0 && (
        <section aria-labelledby="scanned" className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h2 id="scanned" className="text-[length:var(--t-lg)] font-bold">
              Scanned, listing not written yet
            </h2>
            <p className="text-sm text-ink-2">Real 3D scans. The listing agent has not written them up yet.</p>
          </div>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {scans.map((s) => (
              <li key={s.id} className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-2">
                {s.images[0] ? (
                  // eslint-disable-next-line @next/next/no-img-element -- buyer-zone demo files on the shared origin
                  <img src={s.images[0]} alt={s.name} loading="lazy" className="pad aspect-square w-full rounded-md object-contain" />
                ) : (
                  <div aria-hidden className="pad aspect-square w-full rounded-md" />
                )}
                <div className="flex flex-col gap-0.5 px-1 pb-1">
                  <p className="font-semibold">{s.name}</p>
                  {s.note && <p className="text-xs text-ink-2">{s.note}</p>}
                  <p className="text-xs text-ink-2">Waiting for the listing agent</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
