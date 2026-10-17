import { notFound } from "next/navigation";
import { getGarageSale, getListing, getListings, getSeller } from "@/lib/data";
import { formatPrice } from "@/lib/format";
import type { MarketListing } from "@/lib/types";
import SpinViewer from "@/components/SpinViewer";
import VerifiedBadge from "@/components/VerifiedBadge";
import PriceBadge from "@/components/PriceBadge";
import ConditionPill from "@/components/ConditionPill";
import SellerCard from "@/components/SellerCard";
import SaveButton from "@/components/SaveButton";
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
    <section className="mt-10">
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

  return (
    <div className="pb-24 min-[900px]:pb-0">
      <div className="grid gap-8 min-[900px]:grid-cols-12">
        <div className="min-[900px]:col-span-7">
          <div className="flex flex-col gap-3 min-[900px]:sticky min-[900px]:top-4">
            <div className="aspect-square max-w-[640px] bg-surface-2">
              <SpinViewer frames={item.frames} alt={l.title} variant="detail" viewerUrl={l.viewer_url} />
            </div>
            <VerifiedBadge usableViews={item.usable_view_count} />
          </div>
        </div>
        <div className="flex flex-col gap-4 min-[900px]:col-span-5">
          <div className="flex items-start justify-between gap-3">
            <h1 className="text-[length:var(--t-xl)] font-bold">{l.title}</h1>
            <SaveButton itemId={l.item_id} title={l.title} />
          </div>
          <p className="text-[length:var(--t-2xl)] font-bold">{formatPrice(l.price_cad)}</p>
          <PriceBadge price={l.price_cad} reference={item.reference_price_cad} size="lg" />
          <details className="rounded-md border border-line p-3">
            <summary className="cursor-pointer font-semibold">Why this price?</summary>
            <ul className="mt-2 list-disc pl-5 text-sm">
              {l.price_justification.map((j) => <li key={j}>{j}</li>)}
            </ul>
          </details>
          <ConditionPill grade={l.condition_grade} sellerChecking={l.needs_seller_check} />
          {l.condition_notes.length > 0 && (
            <ul className="list-disc pl-5 text-sm">{l.condition_notes.map((n) => <li key={n}>{n}</li>)}</ul>
          )}
          {l.needs_seller_check && (
            <div role="note" className="rounded-md border border-amber bg-amber/20 p-3 text-sm">
              <p className="font-semibold">The seller is double-checking this one.</p>
              <ul className="list-disc pl-5">{l.seller_check_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
          )}
          <div className="hidden min-[900px]:block">
            <ReserveSheet item={item} sale={sale} disabledLabel={disabledLabel} />
          </div>
          <p>{l.description}</p>
          <table className="w-full text-sm">
            <caption className="sr-only">Details</caption>
            <tbody>
              {Object.entries(l.attributes).map(([k, v]) => (
                <tr key={k} className="border-t border-line">
                  <th scope="row" className="py-1.5 pr-4 text-left font-normal capitalize text-ink-2">{k.replace(/_/g, " ")}</th>
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
          <SellerCard seller={seller} sale={sale} />
          <p className="text-sm text-ink-2">Pickup area: {item.location.neighbourhood}, {item.location.city}</p>
        </div>
      </div>
      <Grid label="More from this sale" list={more} />
      <Grid label="Similar items" list={similar} />
      <div className="fixed inset-x-0 bottom-0 z-10 flex items-center gap-4 border-t border-line bg-surface p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] min-[900px]:hidden">
        <span className="text-[length:var(--t-lg)] font-bold">{formatPrice(l.price_cad)}</span>
        <ReserveSheet item={item} sale={sale} disabledLabel={disabledLabel} placement="bar" />
      </div>
    </div>
  );
}
