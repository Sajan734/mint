"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { setMockMode, useMockMode } from "@/lib/mock-mode";

const links = [
  { href: "/saved", label: "Saved" },
  { href: "/orders", label: "Orders" },
  { href: "/about", label: "How it works" },
];

/** The Mint mark: a mint disc with the dashed scan ring. */
export function MintMark({ size = 24 }: { size?: number }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" width={size} height={size} fill="none">
      <circle cx="12" cy="12" r="10" fill="var(--mint)" />
      <circle cx="12" cy="12" r="6.5" stroke="#0b0f0e" strokeWidth="1.5" strokeDasharray="2.2 1.8" />
    </svg>
  );
}

export default function SiteHeader() {
  const path = usePathname();
  const mock = useMockMode();
  // Row 1 on a phone: logo, demo pill, Sell. Row 2: search. Row 3: nav. From md up it is one row: logo, search, nav, Sell.
  return (
    <header className="top-0 z-20 bg-bg md:sticky">
      <div className="mx-auto flex min-h-16 w-full max-w-[1240px] flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2 sm:gap-x-5 sm:px-6 md:min-h-20 lg:px-10">
        {/* aria-label keeps the accessible name "Home" now that Home is not in the nav */}
        <Link href="/" aria-label="Home" className="order-1 flex min-h-11 items-center gap-2 font-display text-xl font-bold tracking-tight">
          <MintMark />
          mint
        </Link>
        {mock && (
          <div className="order-2 flex items-center text-sm">
            <span className="rounded-full bg-amber-wash px-3 py-1 font-semibold text-amber">Demo data</span>
            <button type="button" onClick={() => setMockMode(false)} className="inline-flex min-h-11 items-center px-2 font-medium text-ink-2 underline underline-offset-2 hover:text-ink">
              Turn off
            </button>
          </div>
        )}
        {/* Different zone (the seller app): a plain <a>, never next/link, or the click silently does nothing. */}
        <a href="/sell" aria-label="Sell an item" className="btn-primary order-3 ml-auto min-h-11 px-5 text-sm md:order-5 md:ml-0">
          <span aria-hidden className="sm:hidden">Sell</span>
          <span aria-hidden className="hidden sm:inline">Sell an item</span>
        </a>
        <form role="search" action="/" className="relative order-4 min-w-full pb-1 md:order-3 md:min-w-48 md:max-w-md md:flex-1 md:pb-0">
          <label htmlFor="site-search" className="sr-only">
            Search items
          </label>
          <svg aria-hidden viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="pointer-events-none absolute left-4 top-[22px] -translate-y-1/2 text-ink-2">
            <circle cx="11" cy="11" r="6.5" />
            <path d="m16 16 4 4" />
          </svg>
          <input
            id="site-search"
            name="q"
            type="search"
            placeholder="Search your neighbours' things"
            className="field min-h-11 rounded-full pl-11 pr-4 text-[15px]"
          />
        </form>
        <nav aria-label="Main" className="order-5 min-w-full md:order-4 md:ml-auto md:min-w-0">
          <ul className="flex gap-x-6 text-[15px] font-medium">
            {links.map((l) => {
              const current = path?.startsWith(l.href);
              return (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    aria-current={current ? "page" : undefined}
                    className={`inline-flex min-h-11 items-center underline-offset-[6px] transition-colors ${current ? "font-semibold text-ink underline decoration-2 decoration-leaf" : "text-ink-2 hover:text-ink"}`}
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
