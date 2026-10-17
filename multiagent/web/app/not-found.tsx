import Link from "next/link";

export default function NotFound() {
  return (
    <section className="mx-auto max-w-[56ch] py-20 text-center">
      <svg aria-hidden viewBox="0 0 48 48" width="56" height="56" fill="none" stroke="currentColor" strokeWidth="2" className="mx-auto text-ink-2">
        <circle cx="24" cy="24" r="18" strokeDasharray="4 4" />
        <path d="M17 29c2-3 4-4 7-4s5 1 7 4M18 19v1M30 19v1" strokeLinecap="round" />
      </svg>
      <h1 className="mt-6 text-[length:var(--t-2xl)] font-bold">This page moved on.</h1>
      <p className="mt-3 text-ink-2">We could not find what you were looking for. The item may have sold, or the link may be old.</p>
      <Link href="/" className="mt-8 inline-flex min-h-12 items-center rounded-md bg-ink px-6 font-semibold text-bg">
        Back to home
      </Link>
    </section>
  );
}
