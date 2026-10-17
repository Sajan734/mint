"use client";
import Link from "next/link";
import { NEW_SCAN_HREF } from "@/lib/scan";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ChangeEvent } from "react";
import { MediaProvider, MediaTiles, MediaViewer } from "@/components/MediaPanel";
import PriceBadge from "@/components/PriceBadge";
import { GRADE_LABEL, formatPrice } from "@/lib/format";
import { getLocal, upsertLocal, useLocalListings, type LocalListing, type LocalState } from "@/lib/local-listings";
import { DEMO_SELLER_ID, sampleSplatFor, useMockMode } from "@/lib/mock-mode";
import type { ListingDoc, MarketListing } from "@/lib/types";
import scanResult from "@/mock/scan-result.json";

// The real listing (ThinkPad mouse, gsplat/out/scan_a6816dfc) that demo mode replays for every new scan.
const MOCK_RESULT = scanResult as unknown as MarketListing;

export interface Fields {
  title: string;
  description: string;
  price: string; // as typed
}
export type FieldErrors = Partial<Record<keyof Fields, string>>;
export const TITLE_MAX = 120;

/** Title 1-120 characters, description not empty, price a whole number of dollars >= 1 (buyer/lib/schema.ts). */
export function validateFields(f: Fields): FieldErrors {
  const e: FieldErrors = {};
  const title = f.title.trim();
  if (!title) e.title = "Add a name.";
  else if (title.length > TITLE_MAX) e.title = `Keep the name to ${TITLE_MAX} characters or fewer.`;
  if (!f.description.trim()) e.description = "Add a description.";
  const p = f.price.trim();
  if (!/^\d+$/.test(p) || !Number.isSafeInteger(Number(p)) || Number(p) < 1) e.price = "Enter a whole dollar amount, 1 or more.";
  return e;
}

/**
 * A fresh draft from the agent's output. Demo results get Raj's wrapper, as gsplat/mintsplat/market.py does for live
 * scans; the agent's text and both prices stay as written. Timestamps are filled in when it is saved.
 */
export function seedEntry(id: string, m: MarketListing, source: "mock" | "live"): LocalListing {
  const listing = { ...m.listing, item_id: id };
  const market: MarketListing =
    source === "mock"
      ? {
          ...m,
          listing,
          seller_id: DEMO_SELLER_ID,
          garage_sale_id: "gs_agincourt_tech",
          location: { neighbourhood: "Agincourt", city: "Toronto" },
          status: "available",
        }
      : { ...m, listing };
  return { id, state: "draft", source, suggested_price_cad: m.listing.price_cad, market, created_at: "", updated_at: "" };
}

/** The seller's edits on top of an entry. Never touches reference_price_cad, so the price badge stays honest. */
export function applyEdits(e: LocalListing, f: Fields, state: LocalState, now: string): LocalListing {
  const publish = state === "published";
  const wasPublished = e.state === "published";
  return {
    ...e,
    state,
    created_at: e.created_at || now,
    updated_at: now,
    published_at: publish ? (wasPublished && e.published_at) || now : undefined,
    market: {
      ...e.market,
      listing: { ...e.market.listing, title: f.title.trim(), description: f.description.trim(), price_cad: Number(f.price.trim()) },
      seller_id: DEMO_SELLER_ID,
      status: "available",
      listed_at: publish && !wasPublished ? now : e.market.listed_at,
    },
  };
}

const noSubscribe = () => () => {};

/** The editor from the user's sketch. Data: this device first, then the demo result, then the live document. */
export default function ListingEditor({ id, doc }: { id: string; doc: ListingDoc | null }) {
  const hydrated = useSyncExternalStore(noSubscribe, () => true, () => false);
  const mock = useMockMode();
  const local = useLocalListings().find((l) => l.id === id) ?? null;
  const seed = useMemo(
    () =>
      mock
        ? seedEntry(id, MOCK_RESULT, "mock")
        : doc?.status === "listed" && doc.market_listing
          ? seedEntry(id, doc.market_listing, "live")
          : null,
    [id, mock, doc],
  );

  // First visit after a scan: keep the agent's result on this device as a draft, so the dashboard lists it.
  const needsSeed = hydrated && !local && seed !== null;
  useEffect(() => {
    if (!needsSeed || !seed) return;
    const now = new Date().toISOString();
    upsertLocal({ ...seed, created_at: now, updated_at: now });
  }, [needsSeed, seed]);

  if (!hydrated) return <p className="pt-8 text-ink-2">Loading your listing…</p>;
  const entry = local ?? seed; // seed alone only when this browser blocks storage
  if (!entry) return <NotReady id={id} doc={doc} />;
  return <EditorForm key={id} entry={entry} mock={mock} />;
}

// Today's copy for a scan that has no listing (yet).
function NotReady({ id, doc }: { id: string; doc: ListingDoc | null }) {
  return (
    <div className="flex max-w-xl flex-col gap-4 pt-8">
      <h1 className="text-[length:var(--t-2xl)] font-bold">
        {doc?.status === "rejected" ? "We couldn't list this one" : doc?.status === "failed" ? "Something went wrong" : "Still working on it"}
      </h1>
      <p className="text-ink-2">{doc?.rejection?.match_check.reason ?? doc?.error ?? "Your listing isn't ready yet."}</p>
      {doc ? (
        <a href={NEW_SCAN_HREF} className="btn-primary self-start">
          Scan again
        </a>
      ) : (
        <Link href={`/scan/${id}`} className="btn-primary self-start">
          Back to the scan
        </Link>
      )}
    </div>
  );
}

/** Up to 3 photos: the agent's preview images, else the spin frames at a quarter, half and three quarters. */
function photosFor(m: MarketListing): string[] {
  if (m.listing.preview_images.length) return m.listing.preview_images.slice(0, 3);
  const f = m.frames;
  return [...new Set([0.25, 0.5, 0.75].map((x) => f[Math.floor(f.length * x)]).filter(Boolean))];
}

const FOCUS_ORDER = ["title", "price", "description"] as const; // order on the page

function EditorForm({ entry, mock }: { entry: LocalListing; mock: boolean }) {
  const m = entry.market;
  const l = m.listing;
  const [fields, setFields] = useState<Fields>({ title: l.title, description: l.description, price: String(l.price_cad) });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [toast, setToast] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [published, setPublished] = useState(false);
  const titleRef = useRef<HTMLTextAreaElement>(null);
  const priceRef = useRef<HTMLInputElement>(null);
  const descRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2500);
    return () => clearTimeout(t);
  }, [toast]);

  const set = (k: keyof Fields) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const v = k === "title" ? e.target.value.replace(/\n/g, " ") : e.target.value; // a name is one line
    setFields((f) => ({ ...f, [k]: v }));
    if (errors[k]) setErrors((x) => ({ ...x, [k]: undefined }));
  };

  function save(state: LocalState) {
    const errs = validateFields(fields);
    setErrors(errs);
    setSaveError(null);
    const first = FOCUS_ORDER.find((k) => errs[k]);
    if (first) {
      ({ title: titleRef, price: priceRef, description: descRef })[first].current?.focus();
      return;
    }
    const now = new Date().toISOString();
    const wasPublished = entry.state === "published";
    upsertLocal(applyEdits(entry, fields, state, now));
    if (getLocal(entry.id)?.updated_at !== now) {
      setSaveError("Could not save on this device. This browser is blocking storage.");
      return;
    }
    if (state === "published") setPublished(true);
    else setToast(wasPublished ? "Saved as a draft. Buyers no longer see it." : "Saved");
  }

  if (published) return <Published entry={entry} />;

  const splatUrl = m.splat_url ?? (mock ? sampleSplatFor(entry.id) : null);
  const priceOk = !validateFields({ ...fields, title: "x", description: "x" }).price;
  const fieldCls = (bad: boolean) =>
    `w-full rounded-md border bg-surface px-3 ${bad ? "border-2 border-coral" : "border-line-strong"}`;
  const err = (k: keyof Fields) =>
    errors[k] && (
      <p id={`f-${k}-err`} className="mt-1 flex items-center gap-1.5 text-sm font-semibold">
        <svg aria-hidden viewBox="0 0 24 24" width="16" height="16" className="shrink-0 text-coral">
          <circle cx="12" cy="12" r="10" fill="currentColor" />
          <path d="M12 7v6m0 3.5v.5" stroke="#0b0f0e" strokeWidth="2.5" strokeLinecap="round" />
        </svg>
        {errors[k]}
      </p>
    );
  const aria = (k: keyof Fields) => ({ "aria-invalid": errors[k] ? true : undefined, "aria-describedby": errors[k] ? `f-${k}-err` : undefined });

  return (
    <MediaProvider title={l.title} splatUrl={splatUrl} frames={m.frames} photos={photosFor(m)} sample={!m.splat_url && mock}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-sm">
        <Link href="/" className="inline-flex min-h-11 items-center font-medium text-ink-2 underline-offset-2 hover:text-ink hover:underline">
          ← Your listings
        </Link>
        <p className="font-semibold text-mint-ink">
          {entry.state === "published" ? "Published on this device" : "Draft · written by Mint from your scan"}
        </p>
      </div>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          save("published");
        }}
        className="grid gap-6 md:grid-cols-12 md:gap-x-8"
      >
        <div className="order-1 md:col-span-7">
          <MediaViewer />
        </div>

        <div className="order-3 flex flex-col gap-5 md:order-2 md:col-span-5">
          <div>
            <label htmlFor="f-title" className="text-sm font-semibold text-ink-2">
              Name
            </label>
            {/* A textarea so long agent titles wrap instead of hiding; newlines are turned into spaces. */}
            <textarea
              id="f-title"
              ref={titleRef}
              value={fields.title}
              onChange={set("title")}
              rows={2}
              autoComplete="off"
              {...aria("title")}
              className={`${fieldCls(!!errors.title)} mt-1 block resize-none py-2 font-display text-[length:var(--t-xl)] font-bold leading-tight [field-sizing:content]`}
            />
            {err("title")}
          </div>

          <div className="flex flex-col gap-1">
            <p className="text-ink-2">{`Suggested price ${formatPrice(entry.suggested_price_cad)}`}</p>
            <label htmlFor="f-price" className="mt-2 text-sm font-semibold text-ink-2">
              Your price
            </label>
            <div className={`${fieldCls(!!errors.price)} flex max-w-56 items-center`}>
              <span aria-hidden className="font-display text-[length:var(--t-xl)] font-bold text-ink-2">
                $
              </span>
              <input
                id="f-price"
                ref={priceRef}
                value={fields.price}
                onChange={set("price")}
                inputMode="numeric"
                autoComplete="off"
                {...aria("price")}
                className="min-h-12 w-full bg-transparent pl-1 font-display text-[length:var(--t-xl)] font-bold"
              />
            </div>
            {err("price")}
            {priceOk && (
              <div className="mt-1">
                <PriceBadge price={Number(fields.price)} reference={m.reference_price_cad} size="lg" />
              </div>
            )}
          </div>

          {l.price_justification.length > 0 && (
            <div className="flex flex-col gap-1">
              <h2 className="text-[length:var(--t-md)] font-bold">Why this price?</h2>
              <ul className="list-disc pl-5 text-sm text-ink-2">
                {l.price_justification.map((j) => (
                  <li key={j}>{j}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-col gap-1">
            <h2 className="text-[length:var(--t-md)] font-bold">Condition: {GRADE_LABEL[l.condition_grade]}</h2>
            {l.condition_notes.length > 0 && (
              <ul className="list-disc pl-5 text-sm text-ink-2">
                {l.condition_notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            )}
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
        </div>

        <div className="order-4 md:order-3 md:col-span-12">
          <label htmlFor="f-description" className="text-sm font-semibold text-ink-2">
            Description
          </label>
          <textarea
            id="f-description"
            ref={descRef}
            value={fields.description}
            onChange={set("description")}
            rows={4}
            {...aria("description")}
            className={`${fieldCls(!!errors.description)} mt-1 block py-2`}
          />
          {err("description")}
        </div>

        <div className="order-2 md:order-4 md:col-span-12">
          <MediaTiles />
        </div>

        <div className="order-5 flex flex-wrap items-center justify-end gap-3 md:col-span-12">
          <p role="status" aria-live="polite" className="mr-auto text-sm font-semibold text-mint-ink">
            {toast}
          </p>
          {saveError && (
            <p role="alert" className="w-full text-right text-sm font-semibold">
              {saveError}
            </p>
          )}
          <button type="button" onClick={() => save("draft")} className="btn-secondary min-h-11 px-4 text-sm">
            Save draft
          </button>
          <button type="submit" className="btn-primary">
            Publish
          </button>
        </div>
      </form>
    </MediaProvider>
  );
}

function Published({ entry }: { entry: LocalListing }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const l = entry.market.listing;
  return (
    <section aria-labelledby="published" className="mx-auto flex max-w-xl flex-col items-start gap-5 pt-8">
      <h1 id="published" ref={heading} tabIndex={-1} className="text-[length:var(--t-2xl)] font-bold">
        Published on this device.
      </h1>
      <p className="text-ink-2">
        {l.title} · {formatPrice(l.price_cad)}. Anyone using this browser sees it on Mint now.
      </p>
      <div className="flex flex-wrap gap-3">
        {/* Plain <a>: the listing page lives in the buyer zone, next/link would add /sell. */}
        <a href={`/listing/${entry.id}`} className="btn-primary">
          View listing
        </a>
        <Link href="/" className="btn-secondary">
          Back to your listings
        </Link>
      </div>
    </section>
  );
}
