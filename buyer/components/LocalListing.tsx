"use client";
// The listing page layout (ListingView), shared by the server page and by listings published on this device.
// LocalListing: the server does not know an id published in this browser (lib/local-listings), so the page hands it
// here instead of a 404. Same layout as the seller's editor sketch, read-only.
import Link from "next/link";
import { useSyncExternalStore, type ReactNode } from "react";
import type { GarageSale, MarketListing, Seller } from "@/lib/types";
import { formatPrice } from "@/lib/format";
import { useLocalListings } from "@/lib/local-listings";
import { MediaProvider, MediaTiles, MediaViewer } from "./MediaPanel";
import PriceBadge from "./PriceBadge";
import ConditionPill from "./ConditionPill";
import SellerCard from "./SellerCard";
import SaveAction from "./SaveAction";
import ReserveSheet, { shippingFee } from "./ReserveSheet";
import ContactSeller from "./ContactSeller";

export function ListingView({
  item,
  seller,
  sale,
  note,
  children,
}: {
  item: MarketListing;
  seller: Seller;
  sale: GarageSale;
  note?: string; // small pill above the title, e.g. "Published on this device"
  children?: ReactNode; // related items, below everything
}) {
  const { listing: l } = item;
  const disabledLabel = item.status === "available" ? undefined : item.status === "reserved" ? "Reserved" : "Sold";
  const attrs = Object.entries(l.attributes);

  return (
    <div className="pb-32 pt-2 md:pb-12 md:pt-6">
      {/* preview_images[0] is the first spin frame; the last 3 are the photo tiles (f06, f12, f18 for pots). */}
      <MediaProvider title={l.title} splatUrl={item.splat_url} frames={item.frames} photos={l.preview_images.slice(-3)}>
        {/* Phone: viewer, facts, about + tiles + actions, then reserve and seller. md+: viewer left (7/12); facts, then
            reserve and seller, right (5/12); about + tiles + actions full width below (the editor sketch). */}
        <div className="grid gap-6 md:grid-cols-12 md:gap-x-10 md:gap-y-6">
          <div className="md:col-span-7 md:row-span-2">
            <MediaViewer />
          </div>
          <div className="flex flex-col gap-3 md:col-span-5">
            {note && <p className="self-start rounded-full bg-mint-wash px-2.5 py-1 text-xs font-semibold text-mint-ink">{note}</p>}
            <h1 className="text-balance text-[length:var(--t-xl)] font-bold md:text-[length:var(--t-2xl)]">{l.title}</h1>
            <p className="text-sm text-ink-2">
              {item.location.neighbourhood}, {item.location.city}
            </p>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 pt-1">
              <p className="font-display text-[2.5rem] font-bold leading-none tabular-nums">{formatPrice(l.price_cad)}</p>
              <PriceBadge price={l.price_cad} reference={item.reference_price_cad} size="lg" />
            </div>
            <details className="group mt-1 rounded-md border border-line bg-surface">
              <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 font-semibold [&::-webkit-details-marker]:hidden">
                Why this price?
                <svg aria-hidden viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="transition-transform duration-200 group-open:rotate-180"><path d="m6 9 6 6 6-6" /></svg>
              </summary>
              <ul className="grid gap-2 border-t border-line px-4 py-3 text-sm">
                {l.price_justification.map((j) => (
                  <li key={j} className="flex gap-2"><span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-mint-ink" />{j}</li>
                ))}
              </ul>
            </details>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
              <span className="font-semibold">Condition</span>
              <ConditionPill grade={l.condition_grade} sellerChecking={l.needs_seller_check} />
            </div>
          </div>

          <div className="flex flex-col gap-4 md:col-span-12 md:row-start-3 md:mt-2">
            <section aria-labelledby="about-h" className="flex flex-col gap-4">
              <h2 id="about-h" className="text-[length:var(--t-xl)] font-bold">About this item</h2>
              <p className="max-w-[70ch]">{l.description}</p>
              <MediaTiles />
            </section>
            <div className="flex flex-col gap-2 border-t border-line pt-4 md:items-end">
              <p className="text-sm text-ink-2">Got the item? Scan it to compare with the seller&apos;s scan.</p>
              <div className="flex gap-3">
                <ContactSeller seller={seller} itemTitle={l.title} />
                {/* A route handler makes the comparison id and redirects. A plain <a>: next/link would prefetch it (a new id
                    on every visit) and the client router sometimes drops a soft navigation to a route handler. */}
                <a href={`/listing/${l.item_id}/check`} className="btn-primary flex-1 md:flex-none md:min-w-32">
                  Scan
                </a>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-4 md:col-span-5 md:col-start-8 md:row-start-2 md:self-start">
            <section id="reserve" aria-label="Reserve" className="flex scroll-mt-24 flex-col gap-3 rounded-lg border border-line bg-surface p-4">
              <p className="text-sm text-ink-2">
                {sale.ships ? <>Meet in person, or have it shipped for <strong className="text-ink">{formatPrice(shippingFee(l.attributes))}</strong>.</> : "Pickup only. Meet in person, no fee."}
              </p>
              <div className="hidden md:block">
                <ReserveSheet item={item} sale={sale} disabledLabel={disabledLabel} />
              </div>
              <SaveAction itemId={l.item_id} title={l.title} />
            </section>
            <SellerCard seller={seller} sale={sale} />
          </div>
        </div>
      </MediaProvider>

      <div className="mt-10 grid gap-6 md:grid-cols-12 md:gap-10">
        <section aria-labelledby="trust-h" className="flex flex-col gap-3 self-start rounded-lg bg-mint-wash p-5 md:col-span-7">
          <div className="flex items-start gap-3">
            <svg aria-hidden viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="var(--mint-ink)" strokeWidth="2" className="shrink-0"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" strokeDasharray="3 2" /><path d="m9.5 12 2 2 3-3.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
            <div>
              <h2 id="trust-h" className="text-[length:var(--t-lg)] font-bold text-mint-ink">Scanned by Mint</h2>
              <p className="text-sm text-ink">{item.usable_view_count} views of this item, nothing hidden.</p>
            </div>
          </div>
          {l.condition_notes.length > 0 && (
            <ul className="grid gap-1.5 text-sm">
              {l.condition_notes.map((n) => <li key={n} className="flex gap-2"><span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-ink-2" />{n}</li>)}
            </ul>
          )}
          {l.needs_seller_check && (
            <div role="note" className="rounded-md bg-surface p-3 text-sm">
              <p className="font-semibold">The seller is double-checking this one.</p>
              <ul className="mt-1 list-disc pl-5 text-ink-2">{l.seller_check_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
          )}
        </section>
        {(attrs.length > 0 || l.tags.length > 0) && (
          <section aria-labelledby="details-h" className="flex flex-col gap-3 md:col-span-5">
            <h2 id="details-h" className="text-[length:var(--t-lg)] font-bold">Details</h2>
            <table className="w-full text-sm">
              <caption className="sr-only">Details</caption>
              <tbody>
                {attrs.map(([k, v]) => (
                  <tr key={k} className="border-t border-line">
                    <th scope="row" className="py-2 pr-4 text-left font-normal capitalize text-ink-2">{k.replace(/_/g, " ")}</th>
                    <td>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {l.tags.length > 0 && (
              <ul className="flex list-none flex-wrap gap-2 p-0">
                {l.tags.map((t) => <li key={t} className="rounded-sm bg-surface-2 px-2 py-0.5 text-xs">{t}</li>)}
              </ul>
            )}
          </section>
        )}
      </div>

      {children}

      <div className="fixed inset-x-0 bottom-0 z-10 flex items-center gap-4 border-t border-line bg-surface p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:hidden">
        <span className="font-display text-[length:var(--t-xl)] font-bold tabular-nums">{formatPrice(l.price_cad)}</span>
        <ReserveSheet item={item} sale={sale} disabledLabel={disabledLabel} placement="bar" />
      </div>
    </div>
  );
}

const subscribeNothing = () => () => {};

export default function LocalListing({ id, sellers, sales }: { id: string; sellers: Seller[]; sales: GarageSale[] }) {
  // False on the server and during hydration (the store reads as empty there), so "not found" never flashes.
  const ready = useSyncExternalStore(subscribeNothing, () => true, () => false);
  const entry = useLocalListings().find((e) => e.id === id);
  if (!ready) return <p role="status" className="py-20 text-center text-ink-2">Loading the listing…</p>;

  const seller = entry && sellers.find((s) => s.id === entry.market.seller_id);
  const sale = entry && sales.find((s) => s.id === entry.market.garage_sale_id);
  if (!entry || !seller || !sale) {
    return (
      <section className="mx-auto flex max-w-[56ch] flex-col items-center gap-3 py-20 text-center">
        <h1 className="text-[length:var(--t-2xl)] font-bold">This listing was published on another device.</h1>
        <p className="text-ink-2">Demo listings stay in the browser that published them.</p>
        <Link href="/" className="btn-primary mt-5">
          Back to Mint
        </Link>
      </section>
    );
  }
  const item = { ...entry.market, listing: { ...entry.market.listing, item_id: id } };
  return (
    <ListingView
      item={item}
      seller={seller}
      sale={sale}
      note={entry.state === "draft" ? "Draft, only on this device" : "Published on this device"}
    />
  );
}
