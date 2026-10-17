export const metadata = { title: "About | Mint" };

const steps = [
  ["Scan", "A seller walks around an item with a phone for about 20 seconds."],
  ["3D model", "The photos become a 3D model you can turn and tilt."],
  ["Condition from 12 views", "Mint looks at the item from 12 angles and grades its condition, with notes on what it saw."],
  ["Fair price", "Mint suggests a fair price from the item type and condition."],
  ["Buyer rescan", "At handover, the buyer scans the item again. Mint compares that scan with the listing and says if it looks the same."],
];
const limits = [
  "Small dents and scratches may not show in a scan.",
  "Shiny, glass and clear items scan badly.",
  "The fair price is an estimate, not a quote.",
  "A comparison result is a likely match, not proof.",
  "This demo takes no payments. Orders are saved only in your browser.",
  "The sample listings here are demo data, not live scans.",
];

export default function AboutPage() {
  return (
    <article className="mx-auto max-w-[720px] py-10 md:py-16">
      <h1 className="text-balance text-[length:var(--t-2xl)] font-bold md:text-[length:var(--t-3xl)]">How Mint works</h1>
      <p className="mt-4 max-w-[56ch] text-[length:var(--t-lg)] text-ink-2">
        You find a lamp online. The photos look fine. Then it arrives with a crack the photos never showed. Mint exists so that does not happen: you see the whole item, from every side, before you hand over money.
      </p>
      <ol className="my-12 grid list-none gap-8 p-0">
        {steps.map(([t, d], i) => (
          <li key={t} className="flex gap-5">
            <span aria-hidden className="grid size-11 shrink-0 place-items-center rounded-full border-2 border-mint-ink bg-mint-wash font-mono text-[length:var(--t-lg)] text-mint-ink">{i + 1}</span>
            <div>
              <h2 className="text-[length:var(--t-xl)] font-bold">{t}</h2>
              <p className="mt-1 max-w-[56ch]">{d}</p>
            </div>
          </li>
        ))}
      </ol>
      <section aria-labelledby="limits-h" className="rounded-lg bg-surface-2 p-6">
        <h2 id="limits-h" className="text-[length:var(--t-xl)] font-bold">What Mint cannot do</h2>
        <p className="mt-1 text-ink-2">We would rather tell you now than surprise you later.</p>
        <ul className="mt-4 grid gap-2 pl-5" style={{ listStyle: "disc" }}>
          {limits.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </section>
    </article>
  );
}
