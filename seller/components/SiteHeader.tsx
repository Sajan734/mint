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
    <header className="sticky top-0 z-20 border-b border-line bg-bg">
      <div className="mx-auto flex min-h-14 w-full max-w-[1200px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1 md:min-h-16 md:px-6 lg:px-8">
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- "/" is the buyer zone's landing page */}
        <a href="/" className="flex min-h-11 items-center gap-2 font-display text-xl font-bold tracking-tight">
          <svg aria-hidden viewBox="0 0 24 24" width="24" height="24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--mint)" />
            <circle cx="12" cy="12" r="6.5" stroke="#0b0f0e" strokeWidth="1.5" strokeDasharray="2.2 1.8" />
          </svg>
          mint
        </a>
        <span className="rounded-sm bg-mint-wash px-2 py-0.5 text-xs font-semibold text-mint-ink">Seller</span>
        {mock && (
          <div className="flex items-center text-xs">
            <span className="rounded-full bg-amber/30 px-2.5 py-1 font-semibold">Demo data</span>
            <button type="button" onClick={() => setMockMode(false)} className="inline-flex min-h-11 items-center px-2 font-medium underline underline-offset-2">
              Turn off
            </button>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- "/" is the buyer zone's landing page */}
          <a href="/" className="inline-flex min-h-11 items-center px-2 text-sm font-medium text-ink-2 hover:text-ink">
            Back to Mint
          </a>
          {!onDashboard && (
            <a href={NEW_SCAN_HREF} className="btn-primary text-sm">
              New listing
            </a>
          )}
        </div>
      </div>
    </header>
  );
}
