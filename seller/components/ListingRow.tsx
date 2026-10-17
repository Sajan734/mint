import Link from "next/link";
import PriceBadge from "@/components/PriceBadge";
import { formatPrice } from "@/lib/format";
import type { LocalListing } from "@/lib/local-listings";
import type { ListingStatus, MarketListing } from "@/lib/types";

export type RowStatus = "draft" | ListingStatus;
export interface DashRow {
  id: string;
  title: string;
  price: number;
  reference: number | null;
  thumb: string | null;
  status: RowStatus;
  date: string; // ISO: saved (drafts) or listed
  source: "local" | "mock";
}

const byDateDesc = (a: DashRow, b: DashRow) => b.date.localeCompare(a.date);

/** This device's drafts and listings first, then the demo listings. Same id: this device wins. */
export function buildRows(local: readonly LocalListing[], mock: readonly MarketListing[]): DashRow[] {
  const mine: DashRow[] = local.map((e) => ({
    id: e.id,
    title: e.market.listing.title,
    price: e.market.listing.price_cad,
    reference: e.market.reference_price_cad,
    thumb: e.market.listing.preview_images[0] ?? e.market.frames[0] ?? null,
    status: e.state === "draft" ? "draft" : e.market.status,
    date: e.state === "draft" ? e.updated_at : (e.published_at ?? e.market.listed_at),
    source: "local",
  }));
  const seen = new Set(mine.map((r) => r.id));
  const demo: DashRow[] = mock
    .filter((m) => !seen.has(m.listing.item_id))
    .map((m) => ({
      id: m.listing.item_id,
      title: m.listing.title,
      price: m.listing.price_cad,
      reference: m.reference_price_cad,
      thumb: m.listing.preview_images[0] ?? m.frames[0] ?? null,
      status: m.status,
      date: m.listed_at,
      source: "mock",
    }));
  return [...mine.sort(byDateDesc), ...demo.sort(byDateDesc)];
}

export function countByStatus(rows: readonly DashRow[]): Record<RowStatus, number> {
  const n: Record<RowStatus, number> = { draft: 0, available: 0, reserved: 0, sold: 0 };
  for (const r of rows) n[r.status] += 1;
  return n;
}

export const STATUS_WORD: Record<RowStatus, string> = { draft: "Draft", available: "Listed", reserved: "Reserved", sold: "Sold" };

const PILL: Record<RowStatus, { cls: string; icon: string }> = {
  draft: { cls: "bg-surface-2 text-ink border-dashed border-line-strong", icon: "M4 20h4L19 9l-4-4L4 16v4Zm9-13 4 4" },
  available: { cls: "bg-mint-wash text-mint-ink border-transparent", icon: "M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8ZM7.5 7.5h.01" },
  reserved: { cls: "bg-amber/25 text-ink border-transparent", icon: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" },
  sold: { cls: "bg-ink text-bg border-transparent", icon: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-12.5 0 2.5 2.5 5-5" },
};

export function StatusPill({ status }: { status: RowStatus }) {
  const p = PILL[status];
  return (
    <span className={`inline-flex h-6 items-center gap-1 rounded-sm border px-1.5 text-xs font-semibold ${p.cls}`}>
      <svg aria-hidden viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round">
        <path d={p.icon} />
      </svg>
      {STATUS_WORD[status]}
    </span>
  );
}

const day = new Intl.DateTimeFormat("en-CA", { month: "short", day: "numeric" });
const shortDate = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : day.format(d);
};

// Only what the data says. There are no order records for this seller, so no buyer names or pickup times.
// Reserved rows say "Reserved" through the pill alone.
const saleLine = (r: DashRow) =>
  r.status === "sold" ? `Sold for ${formatPrice(r.price)}` : r.status === "available" ? "No offers yet" : null;

export default function ListingRow({ row }: { row: DashRow }) {
  const local = row.source === "local";
  const when = shortDate(row.date);
  const meta = [saleLine(row), when && `${row.status === "draft" ? "Saved" : "Listed"} ${when}`].filter(Boolean).join(" · ");
  return (
    <li className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-3 py-4 sm:grid-cols-[5rem_minmax(0,1fr)_auto] sm:items-center sm:gap-x-4">
      {row.thumb ? (
        // eslint-disable-next-line @next/next/no-img-element -- buyer-zone frames on the shared origin
        <img src={row.thumb} alt="" loading="lazy" className="pad aspect-square w-full rounded-md object-contain" />
      ) : (
        <div aria-hidden className="pad aspect-square w-full rounded-md" />
      )}

      <div className="flex min-w-0 flex-col gap-1">
        <p className="truncate font-semibold">{row.title}</p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-display text-[length:var(--t-lg)] font-bold">{formatPrice(row.price)}</span>
          <PriceBadge price={row.price} reference={row.reference} />
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-2">
          <StatusPill status={row.status} />
          {meta && <p>{meta}</p>}
          <span className="rounded-sm border border-line px-1.5 text-xs">{local ? "On this device" : "Demo data"}</span>
        </div>
      </div>

      <div className="col-start-2 flex gap-2 sm:col-start-auto sm:justify-end">
        {row.status === "draft" ? (
          <Link href={`/listing/${row.id}`} className="btn-primary text-sm" aria-label={`Finish listing: ${row.title}`}>
            Finish listing
          </Link>
        ) : (
          <>
            {local && (
              <Link href={`/listing/${row.id}`} className="btn-secondary text-sm" aria-label={`Edit: ${row.title}`}>
                Edit
              </Link>
            )}
            {/* Plain <a>: the listing page lives in the buyer zone, next/link would add /sell. */}
            <a href={`/listing/${row.id}`} className="btn-secondary text-sm" aria-label={`View: ${row.title}`}>
              View
            </a>
          </>
        )}
      </div>
    </li>
  );
}
