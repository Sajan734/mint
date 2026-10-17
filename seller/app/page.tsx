import Link from "next/link";

const HOW = [
  { title: "Scan", body: "Click Scan an item, point your iPhone at the code and record a 20-second turn around it." },
  { title: "We write it", body: "Mint builds a 3D scan, names the item, describes it, checks its condition and suggests a fair price." },
  { title: "You publish", body: "Review the draft, adjust if you like, and it's live with a 360° view buyers can trust." },
];

export default function Home() {
  return (
    <div className="flex flex-col gap-16 pt-8 md:pt-16">
      <section className="flex max-w-2xl flex-col gap-5">
        <h1 className="text-[length:var(--t-3xl)] font-bold">Sell it with a 20-second scan.</h1>
        <p className="text-[length:var(--t-lg)] text-ink-2">
          No photos to take, no description to write, no guessing the price. Scan the item with your phone and Mint
          does the rest.
        </p>
        <div>
          <Link href="/scan/new" className="btn-primary">
            Scan an item
          </Link>
        </div>
      </section>

      <section aria-labelledby="how" className="flex flex-col gap-6">
        <h2 id="how" className="text-[length:var(--t-xl)] font-bold">
          How it works
        </h2>
        <ol className="grid gap-4 md:grid-cols-3">
          {HOW.map((s, i) => (
            <li key={s.title} className="rounded-lg border border-line bg-surface p-5">
              <p className="font-mono text-sm text-mint-ink">0{i + 1}</p>
              <p className="mt-1 font-display text-[length:var(--t-lg)] font-bold">{s.title}</p>
              <p className="mt-2 text-sm text-ink-2">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
