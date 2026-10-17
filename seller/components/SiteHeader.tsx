import Link from "next/link";

export default function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-bg">
      <div className="mx-auto flex min-h-14 w-full max-w-[1200px] items-center gap-3 px-4 md:min-h-16 md:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-2 font-display text-xl font-bold tracking-tight">
          <svg aria-hidden viewBox="0 0 24 24" width="24" height="24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--mint)" />
            <circle cx="12" cy="12" r="6.5" stroke="#0b0f0e" strokeWidth="1.5" strokeDasharray="2.2 1.8" />
          </svg>
          mint
        </Link>
        <span className="rounded-sm bg-mint-wash px-2 py-0.5 text-xs font-semibold text-mint-ink">Seller</span>
        <Link href="/scan/new" className="btn-primary ml-auto min-h-10 text-sm">
          Scan an item
        </Link>
      </div>
    </header>
  );
}
