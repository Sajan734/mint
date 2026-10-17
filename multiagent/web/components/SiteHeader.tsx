"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Home" },
  { href: "/saved", label: "Saved" },
  { href: "/orders", label: "Orders" },
  { href: "/about", label: "How it works" },
];

export default function SiteHeader() {
  const path = usePathname();
  const onHome = path === "/";
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-bg">
      <div className="mx-auto flex min-h-14 w-full max-w-[1200px] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-1 md:min-h-16 md:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-2 font-display text-xl font-bold tracking-tight">
          <svg aria-hidden viewBox="0 0 24 24" width="24" height="24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--mint)" />
            <circle cx="12" cy="12" r="6.5" stroke="#0b0f0e" strokeWidth="1.5" strokeDasharray="2.2 1.8" />
          </svg>
          mint
        </Link>
        <nav aria-label="Main" className="ml-auto md:order-3 md:ml-0">
          <ul className="flex gap-x-4 text-sm font-medium md:gap-x-5">
            {links.map((l) => {
              const current = l.href === "/" ? onHome : path?.startsWith(l.href);
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
        {!onHome && (
          <form role="search" action="/" className="order-last min-w-full flex-1 pb-2 md:order-2 md:ml-auto md:min-w-40 md:max-w-xs md:pb-0">
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
        )}
      </div>
    </header>
  );
}
