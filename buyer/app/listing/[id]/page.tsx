import { notFound } from "next/navigation";
import { getGarageSale, getListing, getListings, getSeller } from "@/lib/data";
import { formatPrice } from "@/lib/format";
import type { MarketListing } from "@/lib/types";
import SpinViewer from "@/components/SpinViewer";
import PriceBadge from "@/components/PriceBadge";
import ConditionPill from "@/components/ConditionPill";
import SellerCard from "@/components/SellerCard";
import SaveButton from "@/components/SaveButton";
import SaveAction from "@/components/SaveAction";
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import ReserveSheet from "@/components/ReserveSheet";

export async function generateStaticParams() {
  return (await getListings()).map((m) => ({ id: m.listing.item_id }));
}

async function Grid({ label, list }: { label: string; list: MarketListing[] }) {
  if (!list.length) return null;
  const cards = await Promise.all(
    list.map(async (m) => {
      const [s, g] = await Promise.all([getSeller(m.seller_id), getGarageSale(m.garage_sale_id)]);
      if (!s || !g) return null;
      return (
        <ListingCard
          key={m.listing.item_id}
          item={m}
          seller={s}
          sale={g}
          saveSlot={<SaveButton itemId={m.listing.item_id} title={m.listing.title} />}
        />
      );
    }),
  );
  return (
    <section className="mt-16">
      <h2 className="mb-4 text-[length:var(--t-xl)] font-bold">{label}</h2>
      <ListingGrid label={label}>{cards}</ListingGrid>
    </section>
  );
}

export default async function ListingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const item = await getListing(id);
  if (!item) notFound();
  const { listing: l } = item;
  const [seller, sale, all] = await Promise.all([
    getSeller(item.seller_id),
    getGarageSale(item.garage_sale_id),
    getListings(),
  ]);
  if (!seller || !sale) notFound();
  const others = all.filter((m) => m.listing.item_id !== id);
  const more = others.filter((m) => m.garage_sale_id === sale.id).slice(0, 4);
  const similar = others.filter((m) => m.category === item.category && !more.includes(m)).slice(0, 4);
  const disabledLabel = item.status === "available" ? undefined : item.status === "reserved" ? "Reserved" : "Sold";

  const fee = l.attributes.size_class?.toLowerCase() === "large" ? 25 : 12;
  const dots = { like_new: 4, light_wear: 3, moderate_wear: 2, heavy_wear: 1 }[l.condition_grade];
  const attrs = Object.entries(l.attributes);

  return (
    <div className="pb-32 pt-6 min-[900px]:pb-12 min-[900px]:pt-10 [scroll-padding-bottom:8rem]">
      <div className="grid gap-8 min-[900px]:grid-cols-12 min-[900px]:gap-12">
        <div className="min-[900px]:col-span-7">
          <div className="flex flex-col gap-4 min-[900px]:sticky min-[900px]:top-24">
            <div className="aspect-square w-full max-w-[680px] overflow-hidden rounded-lg bg-surface-2">
              <SpinViewer frames={item.frames} alt={l.title} variant="detail" viewerUrl={l.viewer_url} />
            </div>
            <p className="text-sm text-ink-2">Drag, swipe or use the arrow keys to turn it. Every angle is a real scan frame.</p>
          </div>
        </div>

        <div className="flex flex-col gap-6 min-[900px]:col-span-5">
          <header className="flex flex-col gap-3">
            <h1 className="text-balance text-[length:var(--t-2xl)] font-bold min-[900px]:text-[2.25rem]">{l.title}</h1>
            <p className="text-sm text-ink-2">{item.location.neighbourhood}, {item.location.city}</p>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 pt-2">
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
          </header>

          <section aria-label="Reserve" className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <p className="text-sm text-ink-2">
              {sale.ships ? <>Meet in person, or have it shipped for <strong className="text-ink">{formatPrice(fee)}</strong>.</> : "Pickup only. Meet in person, no fee."}
            </p>
            <div className="hidden min-[900px]:block">
              <ReserveSheet item={item} sale={sale} disabledLabel={disabledLabel} />
            </div>
            <div className="flex gap-3">
              <SaveAction itemId={l.item_id} title={l.title} />
              <button type="button" disabled className="min-h-11 flex-1 rounded-md border border-dashed border-line px-3 text-ink-2 disabled:cursor-not-allowed">
                Message (demo)
              </button>
            </div>
          </section>

          <section aria-labelledby="trust-h" className="flex flex-col gap-4 rounded-lg bg-mint-wash p-5">
            <div className="flex items-start gap-3">
              <svg aria-hidden viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="var(--mint-ink)" strokeWidth="2" className="shrink-0"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" strokeDasharray="3 2" /><path d="m9.5 12 2 2 3-3.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <div>
                <h2 id="trust-h" className="text-[length:var(--t-lg)] font-bold text-mint-ink">Scanned by Mint</h2>
                <p className="text-sm text-ink">{item.usable_view_count} views of this item, nothing hidden.</p>
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold">Condition</span>
                <ConditionPill grade={l.condition_grade} sellerChecking={l.needs_seller_check} />
              </div>
              <div aria-hidden className="grid grid-cols-4 gap-1">
                {[0, 1, 2, 3].map((i) => <span key={i} className={`h-1.5 rounded-full ${i < dots ? "bg-mint-ink" : "bg-line"}`} />)}
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

          <SellerCard seller={seller} sale={sale} />

          <section aria-labelledby="about-h" className="flex flex-col gap-3">
            <h2 id="about-h" className="text-[length:var(--t-xl)] font-bold">About this item</h2>
            <p className="max-w-[62ch]">{l.description}</p>
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
        </div>
      </div>
      <Grid label="More from this sale" list={more} />
      <Grid label="Similar items" list={similar} />
      <div className="fixed inset-x-0 bottom-0 z-10 flex items-center gap-4 border-t border-line bg-surface p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] min-[900px]:hidden">
        <span className="font-display text-[length:var(--t-xl)] font-bold tabular-nums">{formatPrice(l.price_cad)}</span>
        <ReserveSheet item={item} sale={sale} disabledLabel={disabledLabel} placement="bar" />
      </div>
    </div>
  );
}
