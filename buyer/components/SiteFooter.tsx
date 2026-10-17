// Twin: seller/components/SiteFooter.tsx (keep identical)
// Plain <a> links throughout: the footer is shared by both zones and next/link cannot cross them.
// The close of every page (docs/design/DESIGN.md §4): a pine field, the name set large, a few plain links.
const LINKS = [
  { href: "/", label: "Shop" },
  { href: "/sell", label: "Sell an item" },
  { href: "/about", label: "How Mint works" },
  { href: "/saved", label: "Saved" },
  { href: "/orders", label: "Orders" },
];

export default function SiteFooter() {
  return (
    <footer className="bg-pine text-on-pine">
      <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-10 px-4 pb-10 pt-16 sm:px-6 lg:px-10 lg:pt-24">
        <div className="grid gap-8 md:grid-cols-[1.4fr_1fr] md:items-end">
          <p className="max-w-[34ch] text-[length:var(--t-lg)] leading-relaxed text-on-pine">
            Second-hand from your neighbours. Every item is scanned in 3D on the seller&apos;s phone, so you can see
            every side, and Mint checks that the price is fair.
          </p>
          <nav aria-label="Footer">
            <ul className="flex flex-wrap gap-x-6 gap-y-1 md:justify-end">
              {LINKS.map((l) => (
                <li key={l.href}>
                  <a href={l.href} className="inline-flex min-h-11 items-center font-semibold text-ink underline-offset-4 hover:underline">
                    {l.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </div>
        <p aria-hidden className="font-display text-[clamp(5rem,22vw,17rem)] font-bold leading-[0.8] tracking-tight text-ink">
          mint
        </p>
        <p className="text-sm text-on-pine-2">
          A Hack the Valley 11 project. Items marked &ldquo;Demo data&rdquo; are samples, not real listings.
        </p>
      </div>
    </footer>
  );
}
