import Link from "next/link";

const links = [
  { href: "/", label: "Home" },
  { href: "/saved", label: "Saved" },
  { href: "/orders", label: "Orders" },
  { href: "/about", label: "How it works" },
];

export default function SiteHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-bg">
      <div className="mx-auto flex min-h-14 w-full max-w-[1200px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2 md:min-h-16 md:px-6 lg:px-8">
        <Link href="/" className="font-display text-xl font-bold tracking-tight">
          mint
        </Link>
        <nav aria-label="Main">
          <ul className="flex flex-wrap gap-x-5 text-sm font-medium">
            {links.map((l) => (
              <li key={l.href}>
                <Link
                  href={l.href}
                  className="inline-flex min-h-11 items-center text-ink-2 hover:text-ink"
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <form role="search" className="ml-auto min-w-40 flex-1 md:max-w-xs">
          <label htmlFor="site-search" className="sr-only">
            Search items
          </label>
          <input
            id="site-search"
            type="search"
            placeholder="Search items"
            className="min-h-11 w-full rounded-sm border border-line bg-surface px-3 text-sm"
          />
        </form>
      </div>
    </header>
  );
}
