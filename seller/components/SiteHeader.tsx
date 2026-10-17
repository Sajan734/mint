"use client";
import { NEW_SCAN_HREF } from "@/lib/scan";
import { usePathname } from "next/navigation";
import { setMockMode, useMockMode } from "@/lib/mock-mode";

// Seller zone (served under /sell). To leave the zone (the shared landing page at "/") use a plain <a>: next/link
// cannot cross zones. New listing is a plain <a> too (NEW_SCAN_HREF: it goes to a route handler, not a page).
export default function SiteHeader() {
  const mock = useMockMode();
  // "Your listings" (/sell) has its own New listing button in the page, so the header leaves it out there.
  const onDashboard = usePathname() === "/";
  return (
    <header className="sticky top-0 z-20 bg-bg">
      <div className="mx-auto flex min-h-16 w-full max-w-[1240px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 sm:px-6 md:min-h-20 lg:px-10">
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- "/" is the buyer zone's landing page */}
        <a href="/" className="flex min-h-11 items-center gap-2.5 font-display text-[1.75rem] leading-none">
          {/* The Mint seal (twin of MintMark in buyer/components/SiteHeader.tsx). */}
          <svg aria-hidden viewBox="0 0 32 32" width="28" height="28" fill="none">
            <circle cx="16" cy="16" r="16" fill="var(--pine)" />
            <circle cx="16" cy="16" r="9.5" stroke="var(--spark)" strokeWidth="2.4" strokeDasharray="3.2 2.6" strokeLinecap="round" />
            <circle cx="16" cy="16" r="3.2" fill="var(--spark)" />
          </svg>
          mint
        </a>
        <span className="text-[15px] font-medium text-ink-2">for sellers</span>
        {mock && (
          <div className="flex items-center text-sm">
            <span className="rounded-full bg-amber-wash px-3 py-1 font-semibold text-amber">Demo data</span>
            <button type="button" onClick={() => setMockMode(false)} className="inline-flex min-h-11 items-center px-2 font-medium text-ink-2 underline underline-offset-2 hover:text-ink">
              Turn off
            </button>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- "/" is the buyer zone's landing page */}
          <a href="/" className="inline-flex min-h-11 items-center px-2 text-[15px] font-medium text-ink-2 hover:text-ink">
            Back to Mint
          </a>
          {!onDashboard && (
            <a href={NEW_SCAN_HREF} className="btn-primary min-h-11 px-5 text-sm">
              New listing
            </a>
          )}
        </div>
      </div>
    </header>
  );
}
