"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { formatPrice } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { FulfilmentMethod, GarageSale, MarketListing } from "@/lib/types";
import styles from "./ReserveSheet.module.css";

// --- pure logic (tested) ---
export const POSTAL_RE = /^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d$/i;
export const SHIP_FEE = { small: 12, large: 25 } as const;

export const shippingFee = (attrs: Record<string, string>): number =>
  attrs.size_class?.toLowerCase() === "large" ? SHIP_FEE.large : SHIP_FEE.small;

export interface Address { name: string; street: string; city: string; postal_code: string }
export type AddressErrors = Partial<Record<keyof Address, string>>;

export function validateAddress(a: Address): AddressErrors {
  const e: AddressErrors = {};
  if (!a.name.trim()) e.name = "Enter your full name.";
  if (!a.street.trim()) e.street = "Enter your street address.";
  if (!a.city.trim()) e.city = "Enter your city.";
  if (!a.postal_code.trim()) e.postal_code = "Enter your postal code.";
  else if (!POSTAL_RE.test(a.postal_code.trim())) e.postal_code = "Use a Canadian postal code like M5V 2T6.";
  return e;
}

/** Error messages for the chosen method's step-2 inputs ({} when valid). */
export function validateStep2(method: FulfilmentMethod, slot: string, a: Address): Record<string, string> {
  if (method === "meetup") return slot ? {} : { slot: "Pick a pickup time." };
  return validateAddress(a);
}

export const orderTotal = (price: number, method: FulfilmentMethod, fee: number): number =>
  price + (method === "shipping" ? fee : 0);

// --- UI ---
const slotLabel = (iso: string) =>
  new Date(iso).toLocaleString("en-CA", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const FIELDS: { key: keyof Address; label: string; auto: string }[] = [
  { key: "name", label: "Full name", auto: "name" },
  { key: "street", label: "Street address", auto: "street-address" },
  { key: "city", label: "City", auto: "address-level2" },
  { key: "postal_code", label: "Postal code", auto: "postal-code" },
];
const btn = "inline-flex min-h-11 items-center justify-center rounded-md px-5 font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)]";
const primary = `${btn} bg-ink text-bg disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-2`;
const STEPS = ["Delivery", "Details", "Confirm"];

const Alert = () => (
  <svg aria-hidden viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="mt-0.5 shrink-0">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v5M12 16.5v.01" />
  </svg>
);

export default function ReserveSheet({
  item,
  sale,
  disabledLabel,
  placement = "panel",
}: {
  item: MarketListing;
  sale: GarageSale;
  /** Set when the listing can't be reserved ("Reserved", "Sold"). */
  disabledLabel?: string;
  placement?: "panel" | "bar";
}) {
  const router = useRouter();
  const { createOrder } = useStore();
  const dlg = useRef<HTMLDialogElement>(null);
  const summary = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [method, setMethod] = useState<FulfilmentMethod>("meetup");
  const [slot, setSlot] = useState("");
  const [addr, setAddr] = useState<Address>({ name: "", street: "", city: "", postal_code: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [doneId, setDoneId] = useState<string | null>(null);
  const { listing: l } = item;
  const fee = shippingFee(l.attributes);
  const total = orderTotal(l.price_cad, method, fee);

  // Content renders only while open (slot times are timezone-dependent, so no SSR text).
  useEffect(() => {
    if (open && !dlg.current?.open) dlg.current?.showModal();
  }, [open]);
  useEffect(() => {
    if (Object.keys(errors).length) summary.current?.focus();
  }, [errors]);

  const close = () => dlg.current?.close();
  const next = () => {
    const e = step === 2 ? validateStep2(method, slot, addr) : {};
    setErrors(e);
    if (!Object.keys(e).length) setStep(step + 1);
  };
  const confirm = () => {
    const o = createOrder({
      id: crypto.randomUUID(),
      item_id: l.item_id,
      created_at: new Date().toISOString(),
      method,
      ...(method === "meetup" ? { pickup_slot: slot } : { ship_to: { ...addr } }),
      price_cad: l.price_cad,
      shipping_cad: method === "shipping" ? fee : 0,
    });
    setDoneId(o.id);
  };
  const viewOrder = () => {
    const id = doneId;
    close();
    if (id) router.push(`/orders/${id}`);
  };
  // Inline validation: flag on blur, clear while typing (never clear on blur, or the layout shifts under the click).
  const flagField = (key: keyof Address, value: Address) => {
    const msg = validateAddress(value)[key];
    setErrors((prev) => {
      const rest = { ...prev };
      delete rest[key];
      return msg ? { ...rest, [key]: msg } : rest;
    });
  };
  const flagIfInvalid = (key: keyof Address) => {
    const msg = validateAddress(addr)[key];
    if (msg) setErrors((prev) => ({ ...prev, [key]: msg }));
  };

  const errList = Object.values(errors);
  const radio = (m: FulfilmentMethod, title: string, sub: string, off = false) => (
    <label className={`flex min-h-[72px] items-center gap-3 rounded-md border p-4 has-[:checked]:border-ink has-[:checked]:bg-surface-2 ${off ? "cursor-not-allowed border-line opacity-50" : "cursor-pointer border-line hover:border-ink-2"}`}>
      <input type="radio" name="method" value={m} checked={method === m} disabled={off} onChange={() => setMethod(m)} className="size-5 accent-[var(--ink)]" />
      <span><span className="block font-semibold">{title}</span><span className="text-sm text-ink-2">{sub}</span></span>
    </label>
  );
  const titleId = `rs-title-${placement}`;

  return (
    <>
      <button
        type="button"
        disabled={!!disabledLabel}
        onClick={() => { setStep(1); setErrors({}); setDoneId(null); setOpen(true); }}
        className={`${primary} ${placement === "bar" ? "min-h-14 flex-1" : "min-h-14 w-full text-[length:var(--t-lg)]"}`}
      >
        {disabledLabel ?? `Reserve for ${formatPrice(l.price_cad)}`}
      </button>
      <dialog
        ref={dlg}
        aria-labelledby={titleId}
        onClose={() => setOpen(false)}
        onClick={(e) => { if (e.target === dlg.current) close(); }}
        className={`${styles.sheet} fixed inset-x-0 bottom-0 top-auto m-0 max-h-[90vh] w-full max-w-none overflow-y-auto rounded-t-lg border border-line bg-surface p-5 text-ink shadow-[var(--shadow-sheet)] sm:inset-auto sm:m-auto sm:max-w-[480px] sm:rounded-lg sm:p-6`}
      >
        {open && doneId && (
          <div className="flex flex-col items-center gap-4 py-2 text-center" role="status">
            <svg aria-hidden viewBox="0 0 48 48" width="72" height="72" fill="none" stroke="var(--mint-ink)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <circle className={styles.ring} cx="24" cy="24" r="20" />
              <path className={styles.tick} d="m15 25 6 6 12-14" />
            </svg>
            <h2 id={titleId} className="text-[length:var(--t-xl)] font-bold">Reserved. It is yours.</h2>
            <p className="text-ink-2">{l.title}</p>
            <ol className="grid w-full list-decimal gap-2 rounded-md bg-surface-2 py-4 pl-9 pr-4 text-left text-sm">
              {method === "meetup" ? (
                <>
                  <li>Meet the seller at {slotLabel(slot)}.</li>
                  <li>Check the item against its 360 scan.</li>
                  <li>Pay at pickup, then verify it in Mint.</li>
                </>
              ) : (
                <>
                  <li>The seller packs it and ships it.</li>
                  <li>It arrives in 3 to 5 days.</li>
                  <li>Rescan it in Mint to verify it matches.</li>
                </>
              )}
            </ol>
            <button type="button" onClick={viewOrder} className={`${primary} w-full`}>View order</button>
            <p className="text-xs text-ink-2">Payment is simulated in this demo.</p>
          </div>
        )}
        {open && !doneId && (
          <div className="flex flex-col gap-5">
            <header className="flex items-center gap-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {item.frames[0] ? <img src={item.frames[0]} alt="" className="size-16 shrink-0 rounded-md bg-surface-2 object-cover" /> : <span aria-hidden className="size-16 shrink-0 rounded-md bg-surface-2" />}
              <div className="min-w-0">
                <h2 id={titleId} className="line-clamp-2 text-[length:var(--t-lg)] font-bold">Reserve: {l.title}</h2>
                <p className="font-display font-bold tabular-nums">{formatPrice(l.price_cad)}</p>
              </div>
            </header>
            <ol aria-label={`Step ${step} of 3`} className="grid grid-cols-3 gap-2">
              {STEPS.map((name, i) => (
                <li key={name} aria-current={i + 1 === step ? "step" : undefined} className="flex flex-col gap-1.5">
                  <span aria-hidden className={`h-1 rounded-full ${i + 1 <= step ? "bg-ink" : "bg-line"}`} />
                  <span className={`text-xs ${i + 1 === step ? "font-semibold" : "text-ink-2"}`}>{i + 1}. {name}</span>
                </li>
              ))}
            </ol>
            {errList.length > 0 && (
              <div ref={summary} tabIndex={-1} role="alert" className="flex gap-2 rounded-sm border border-coral bg-coral/10 p-3 text-sm">
                <Alert />
                <div>
                  <p className="font-semibold">Fix {errList.length === 1 ? "this" : "these"} to continue:</p>
                  <ul className="list-disc pl-5">{errList.map((m) => <li key={m}>{m}</li>)}</ul>
                </div>
              </div>
            )}
            {step === 1 && (
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-2 font-semibold">How do you want it?</legend>
                {radio("meetup", "Meet in person", "Pay at pickup. No fee.")}
                {sale.ships
                  ? radio("shipping", "Ship to me", `Delivered in 3 to 5 days. +${formatPrice(fee)} flat fee.`)
                  : radio("shipping", "Ship to me", "This sale does not ship.", true)}
              </fieldset>
            )}
            {step === 2 && method === "meetup" && (
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-2 font-semibold">Pickup time in {sale.location.neighbourhood}</legend>
                {sale.pickup_slots.length === 0 && <p className="text-sm text-ink-2">No pickup times listed.</p>}
                {sale.pickup_slots.map((s) => (
                  <label key={s} className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-line px-4 hover:border-ink-2 has-[:checked]:border-ink has-[:checked]:bg-surface-2">
                    <input type="radio" name="slot" value={s} checked={slot === s} onChange={() => setSlot(s)} className="size-5 accent-[var(--ink)]" />
                    {slotLabel(s)}
                  </label>
                ))}
              </fieldset>
            )}
            {step === 2 && method === "shipping" && (
              <div className="flex flex-col gap-3">
                {FIELDS.map((f) => (
                  <label key={f.key} className="flex flex-col gap-1 text-sm font-semibold">
                    {f.label}
                    <input
                      required
                      autoComplete={f.auto}
                      value={addr[f.key]}
                      aria-invalid={!!errors[f.key]}
                      aria-describedby={errors[f.key] ? `err-${f.key}` : undefined}
                      onChange={(e) => {
                        const v = { ...addr, [f.key]: e.target.value };
                        setAddr(v);
                        if (errors[f.key]) flagField(f.key, v);
                      }}
                      onBlur={() => addr[f.key] && flagIfInvalid(f.key)}
                      className={`min-h-11 rounded-sm border bg-bg px-3 font-normal ${errors[f.key] ? "border-coral" : "border-line"}`}
                    />
                    {errors[f.key] && <span id={`err-${f.key}`} className="flex gap-1.5 text-sm font-normal text-ink"><Alert />{errors[f.key]}</span>}
                  </label>
                ))}
                <p className="text-sm text-ink-2">Shipping fee: {formatPrice(fee)}</p>
              </div>
            )}
            {step === 3 && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-md bg-surface-2 p-4 text-sm">
                <dt className="text-ink-2">Item</dt><dd>{l.title}</dd>
                <dt className="text-ink-2">Method</dt>
                <dd>{method === "meetup" ? `Meet in person, ${slotLabel(slot)}` : `Ship to ${addr.name}, ${addr.street}, ${addr.city} ${addr.postal_code.toUpperCase()}`}</dd>
                <dt className="text-ink-2">Price</dt><dd>{formatPrice(l.price_cad)}</dd>
                <dt className="text-ink-2">Shipping</dt><dd>{method === "shipping" ? formatPrice(fee) : "Free"}</dd>
                <dt className="border-t border-line pt-2 font-semibold">Total</dt>
                <dd className="border-t border-line pt-2 font-display text-[length:var(--t-lg)] font-bold tabular-nums">{formatPrice(total)}</dd>
              </dl>
            )}
            <p className="text-sm text-ink-2">Payment is simulated in this demo. Mint holds this item for 24 hours.</p>
            <footer className="flex gap-3">
              <button type="button" onClick={step === 1 ? close : () => { setErrors({}); setStep(step - 1); }} className={`${btn} border border-line`}>
                {step === 1 ? "Cancel" : "Back"}
              </button>
              {step < 3 ? (
                <button type="button" onClick={next} className={`${primary} flex-1`}>Continue</button>
              ) : (
                <button type="button" onClick={confirm} className={`${primary} flex-1`}>
                  {method === "shipping" ? `Pay ${formatPrice(total)} and reserve` : `Reserve for ${formatPrice(total)}`}
                </button>
              )}
            </footer>
          </div>
        )}
      </dialog>
    </>
  );
}
