import Link from "next/link";
import { notFound } from "next/navigation";
import Spin from "@/components/Spin";
import { GRADE_LABEL, formatPrice } from "@/lib/format";
import { isScanId } from "@/lib/scan";
import { getPublicJson, listingDocUrl } from "@/lib/supabase";
import type { ListingDoc } from "@/lib/types";

export const dynamic = "force-dynamic";

const BUYER_URL = (process.env.NEXT_PUBLIC_BUYER_URL || "http://localhost:3000").replace(/\/$/, "");

/** The seller's draft: everything the pipeline wrote, ready to review. */
export default async function DraftPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isScanId(id)) notFound();
  const doc = await getPublicJson<ListingDoc>(listingDocUrl(id));

  if (!doc || doc.status !== "listed" || !doc.market_listing) {
    return (
      <div className="flex max-w-xl flex-col gap-4 pt-8">
        <h1 className="text-[length:var(--t-2xl)] font-bold">
          {doc?.status === "rejected" ? "We couldn't list this one" : doc?.status === "failed" ? "Something went wrong" : "Still working on it"}
        </h1>
        <p className="text-ink-2">
          {doc?.rejection?.match_check.reason ?? doc?.error ?? "Your listing isn't ready yet."}
        </p>
        <Link href={doc ? "/scan/new" : `/scan/${id}`} className="btn-primary self-start">
          {doc ? "Scan again" : "Back to the scan"}
        </Link>
      </div>
    );
  }

  const m = doc.market_listing;
  const l = m.listing;
  return (
    <div className="grid items-start gap-10 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="pad grid aspect-square place-items-center rounded-lg border border-line p-4">
        <Spin frames={m.frames} alt={l.title} />
      </section>

      <section className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <p className="text-sm font-semibold text-mint-ink">Draft · written by Mint from your scan</p>
          <h1 className="text-[length:var(--t-2xl)] font-bold">{l.title}</h1>
        </div>

        <div className="rounded-lg border border-line bg-surface p-5">
          <p className="text-sm text-ink-2">Recommended price</p>
          <p className="font-display text-[length:var(--t-3xl)] font-bold">{formatPrice(l.price_cad)}</p>
          <ul className="mt-2 list-disc pl-5 text-sm text-ink-2">
            {l.price_justification.map((j) => (
              <li key={j}>{j}</li>
            ))}
          </ul>
        </div>

        {l.needs_seller_check && (
          <div role="note" className="rounded-md border border-amber bg-surface p-4 text-sm">
            <p className="font-semibold">Please check before publishing</p>
            <ul className="mt-1 list-disc pl-5">
              {l.seller_check_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <h2 className="text-[length:var(--t-lg)] font-bold">Description</h2>
          <p>{l.description}</p>
        </div>

        <div className="flex flex-col gap-2">
          <h2 className="text-[length:var(--t-lg)] font-bold">Condition: {GRADE_LABEL[l.condition_grade]}</h2>
          <ul className="list-disc pl-5 text-sm text-ink-2">
            {l.condition_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>

        {Object.keys(l.attributes).length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
            {Object.entries(l.attributes).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="capitalize text-ink-2">{k.replaceAll("_", " ")}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        )}

        <div className="flex flex-wrap gap-3">
          <a href={`${BUYER_URL}/listing/${id}`} className="btn-primary">
            See it on Mint
          </a>
          <Link href="/scan/new" className="btn-secondary">
            Scan another item
          </Link>
        </div>
        <p className="text-xs text-ink-2">
          Editing the draft and choosing your own price are next. For now every finished scan goes on Mint as written.
        </p>
      </section>
    </div>
  );
}
