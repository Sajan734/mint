"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { setMockMode, useMockMode } from "@/lib/mock-mode";

const links = [
  { href: "/saved", label: "Saved" },
  { href: "/orders", label: "Orders" },
  { href: "/about", label: "How it works" },
];

export default function SiteHeader() {
  const path = usePathname();
  const mock = useMockMode();
  // Row 1 on a phone: logo, demo pill, Sell. Row 2: search. Row 3: nav. From md up it is one row: logo, search, nav, Sell.
  return (
    <header className="top-0 z-20 border-b border-line bg-bg md:sticky">
      <div className="mx-auto flex min-h-14 w-full max-w-[1200px] flex-wrap items-center gap-x-2 gap-y-1 px-4 sm:gap-x-4 py-1 md:min-h-16 md:px-6 lg:px-8">
        {/* aria-label keeps the accessible name "Home" now that Home is not in the nav */}
        <Link href="/" aria-label="Home" className="order-1 flex min-h-11 items-center gap-2 font-display text-xl font-bold tracking-tight">
          <svg aria-hidden viewBox="0 0 24 24" width="24" height="24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--mint)" />
            <circle cx="12" cy="12" r="6.5" stroke="#0b0f0e" strokeWidth="1.5" strokeDasharray="2.2 1.8" />
          </svg>
          mint
        </Link>
        {mock && (
          <div className="order-2 flex items-center text-xs">
            <span className="rounded-full bg-amber/30 px-2.5 py-1 font-semibold">Demo data</span>
            <button type="button" onClick={() => setMockMode(false)} className="inline-flex min-h-11 items-center px-2 font-medium underline underline-offset-2">
              Turn off
            </button>
          </div>
        )}
        {/* Different zone (the seller app): a plain <a>, never next/link, or the click silently does nothing. */}
        <a href="/sell" className="btn-primary order-3 ml-auto text-sm md:order-5 md:ml-0">
          Sell an item
        </a>
        <form role="search" action="/" className="order-4 min-w-full pb-1 md:order-3 md:min-w-40 md:max-w-sm md:flex-1 md:pb-0">
          <label htmlFor="site-search" className="sr-only">
            Search items
          </label>
          <input
            id="site-search"
            name="q"
            type="search"
            placeholder="Search items"
            className="min-h-11 w-full rounded-md border border-line-strong bg-surface px-3 text-sm placeholder:text-ink-2"
          />
        </form>
        <nav aria-label="Main" className="order-5 min-w-full md:order-4 md:ml-auto md:min-w-0">
          <ul className="flex gap-x-5 text-sm font-medium">
            {links.map((l) => {
              const current = path?.startsWith(l.href);
              return (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    aria-current={current ? "page" : undefined}
                    className={`inline-flex min-h-11 items-center border-b-2 transition-colors ${current ? "border-ink text-ink" : "border-transparent text-ink-2 hover:text-ink"}`}
                  >
                    {l.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
