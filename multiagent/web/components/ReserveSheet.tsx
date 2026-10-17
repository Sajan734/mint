"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { formatPrice } from "@/lib/format";
import { useStore } from "@/lib/store";
import type { FulfilmentMethod, GarageSale, MarketListing } from "@/lib/types";

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
    close();
    router.push(`/orders/${o.id}`);
  };

  const errList = Object.values(errors);
  const radio = (m: FulfilmentMethod, title: string, sub: string, off = false) => (
    <label className={`flex min-h-[72px] cursor-pointer items-center gap-3 rounded-md border p-3 has-[:checked]:border-ink has-[:checked]:bg-surface-2 ${off ? "opacity-50" : "border-line"}`}>
      <input type="radio" name="method" value={m} checked={method === m} disabled={off} onChange={() => setMethod(m)} />
      <span><span className="block font-semibold">{title}</span><span className="text-sm text-ink-2">{sub}</span></span>
    </label>
  );
  const titleId = `rs-title-${placement}`;

  return (
    <>
      <button
        type="button"
        disabled={!!disabledLabel}
        onClick={() => { setStep(1); setErrors({}); setOpen(true); }}
        className={`${primary} ${placement === "bar" ? "min-h-14 flex-1" : "w-full"}`}
      >
        {disabledLabel ?? `Reserve for ${formatPrice(l.price_cad)}`}
      </button>
      <dialog
        ref={dlg}
        aria-labelledby={titleId}
        onClose={() => setOpen(false)}
        onClick={(e) => { if (e.target === dlg.current) close(); }}
        className="fixed inset-x-0 bottom-0 top-auto m-0 max-h-[90vh] w-full max-w-none overflow-y-auto rounded-t-lg border border-line bg-surface p-5 text-ink shadow-[var(--shadow-sheet)] backdrop:bg-black/50 sm:inset-auto sm:m-auto sm:max-w-[480px] sm:rounded-lg"
      >
        {open && (
          <div className="flex flex-col gap-4">
            <header>
              <h2 id={titleId} className="text-[length:var(--t-lg)] font-bold">Reserve: {l.title}</h2>
              <p className="text-sm text-ink-2">{formatPrice(l.price_cad)} · step {step} of 3</p>
            </header>
            {errList.length > 0 && (
              <div ref={summary} tabIndex={-1} role="alert" className="rounded-sm border border-coral p-3 text-sm">
                <p className="font-semibold">Fix {errList.length === 1 ? "this" : "these"} to continue:</p>
                <ul className="list-disc pl-5">{errList.map((m) => <li key={m}>{m}</li>)}</ul>
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
                <legend className="mb-2 font-semibold">Pickup time · {sale.location.neighbourhood}</legend>
                {sale.pickup_slots.length === 0 && <p className="text-sm text-ink-2">No pickup times listed.</p>}
                {sale.pickup_slots.map((s) => (
                  <label key={s} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-line px-3 has-[:checked]:border-ink has-[:checked]:bg-surface-2">
                    <input type="radio" name="slot" value={s} checked={slot === s} onChange={() => setSlot(s)} />
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
                      onChange={(e) => setAddr({ ...addr, [f.key]: e.target.value })}
                      className="min-h-11 rounded-sm border border-line bg-bg px-3 font-normal"
                    />
                    {errors[f.key] && <span id={`err-${f.key}`} className="text-sm font-normal text-ink">⚠ {errors[f.key]}</span>}
                  </label>
                ))}
                <p className="text-sm text-ink-2">Shipping fee: {formatPrice(fee)}</p>
              </div>
            )}
            {step === 3 && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-ink-2">Item</dt><dd>{l.title}</dd>
                <dt className="text-ink-2">Method</dt>
                <dd>{method === "meetup" ? `Meet in person, ${slotLabel(slot)}` : `Ship to ${addr.name}, ${addr.street}, ${addr.city} ${addr.postal_code.toUpperCase()}`}</dd>
                <dt className="text-ink-2">Price</dt><dd>{formatPrice(l.price_cad)}</dd>
                <dt className="text-ink-2">Shipping</dt><dd>{method === "shipping" ? formatPrice(fee) : "Free"}</dd>
                <dt className="font-semibold">Total</dt><dd className="font-bold">{formatPrice(total)}</dd>
              </dl>
            )}
            <p className="text-sm text-ink-2">Payment is simulated in this demo.</p>
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
