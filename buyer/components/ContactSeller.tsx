"use client";
// Contact seller: a native modal <dialog> (the browser traps focus and closes it on Escape). Focus goes back to the
// button on close. The details are demo data (@example.com, 555-01xx), labelled as such.
import { useRef } from "react";
import type { Seller } from "@/lib/types";

const telHref = (phone: string) => `tel:${phone.replace(/[^\d+]/g, "")}`;

export default function ContactSeller({ seller, itemTitle }: { seller: Seller; itemTitle: string }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => dlg.current?.close();
  const { email, phone } = seller;

  return (
    <>
      <button ref={trigger} type="button" className="btn-secondary flex-1 md:flex-none" onClick={() => dlg.current?.showModal()}>
        Contact seller
      </button>
      <dialog
        ref={dlg}
        aria-labelledby="contact-title"
        onClose={() => trigger.current?.focus()}
        onClick={(e) => {
          if (e.target === dlg.current) close();
        }}
        className="m-auto w-[calc(100%-2rem)] max-w-sm rounded-lg border border-line bg-surface p-5 text-ink backdrop:bg-[oklch(0.1_0.01_170/0.5)] sm:p-6"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="contact-title" className="text-[length:var(--t-lg)] font-bold">Contact {seller.name}</h2>
            <p className="mt-1 inline-block rounded-full bg-amber/30 px-2.5 py-0.5 text-xs font-semibold">Demo contact details</p>
          </div>
          <button type="button" onClick={close} aria-label="Close" className="-mr-2 -mt-2 grid size-11 shrink-0 place-items-center rounded-md hover:bg-surface-2">
            <svg aria-hidden viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        {email || phone ? (
          <dl className="mt-4 grid gap-3">
            {email && (
              <div>
                <dt className="text-sm text-ink-2">Email</dt>
                <dd>
                  <a href={`mailto:${email}?subject=${encodeURIComponent(`About: ${itemTitle}`)}`} className="inline-flex min-h-11 items-center font-semibold underline underline-offset-2 [overflow-wrap:anywhere]">
                    {email}
                  </a>
                </dd>
              </div>
            )}
            {phone && (
              <div>
                <dt className="text-sm text-ink-2">Phone</dt>
                <dd>
                  <a href={telHref(phone)} className="inline-flex min-h-11 items-center font-semibold tabular-nums underline underline-offset-2">
                    {phone}
                  </a>
                </dd>
              </div>
            )}
          </dl>
        ) : (
          <p className="mt-4 text-ink-2">This seller has no contact details yet.</p>
        )}
        <p className="mt-4 text-sm text-ink-2">
          {seller.name.split(" ")[0]} {seller.response_time}.
        </p>
      </dialog>
    </>
  );
}
