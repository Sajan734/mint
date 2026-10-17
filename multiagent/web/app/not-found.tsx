import Link from "next/link";

export default function NotFound() {
  return (
    <section className="py-16">
      <h1 className="text-[length:var(--t-2xl)] font-bold">This page moved on.</h1>
      <p className="mt-3 text-ink-2">We could not find what you were looking for.</p>
      <Link
        href="/"
        className="mt-6 inline-flex min-h-11 items-center rounded-md bg-ink px-5 text-bg"
      >
        Back to home
      </Link>
    </section>
  );
}
