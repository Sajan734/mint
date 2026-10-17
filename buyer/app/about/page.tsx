import credits from "@/mock/splat-credits.json";

export const metadata = { title: "About | Mint" };

const steps = [
  ["Scan", "The seller sets the item on a sheet of paper and turns it while the Mint app films it, then flips it over for the underside."],
  ["3D model", "The video becomes a 3D model you can turn and tilt on any phone."],
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
    <article className="mx-auto max-w-[880px] py-10 md:py-16">
      <h1 className="text-[length:var(--t-3xl)] leading-[0.98]">How Mint works</h1>
      <p className="mt-6 max-w-[56ch] text-[length:var(--t-lg)] leading-relaxed">
        You find a lamp online. The photos look fine. Then it arrives with a crack the photos never showed. Mint exists so that does not happen: you see the whole item, from every side, before you hand over money.
      </p>
      <ol className="my-14 grid list-none gap-10 p-0 md:gap-12">
        {steps.map(([t, d]) => (
          <li key={t} className="grid gap-2 md:grid-cols-[14rem_1fr] md:gap-8">
            <h2 className="text-[length:var(--t-xl)]">{t}</h2>
            <p className="max-w-[52ch] text-[length:var(--t-lg)] leading-relaxed">{d}</p>
          </li>
        ))}
      </ol>
      <section aria-labelledby="limits-h" className="rounded-[28px] bg-surface p-7 md:p-10">
        <h2 id="limits-h" className="text-[length:var(--t-2xl)]">What Mint cannot do</h2>
        <p className="mt-2 text-ink-2">We would rather tell you now than surprise you later.</p>
        <ul className="mt-6 grid gap-3 pl-5 text-[length:var(--t-lg)]" style={{ listStyle: "disc" }}>
          {limits.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </section>
      <section id="credits" aria-labelledby="credits-h" className="mt-14 flex flex-col gap-4">
        <h2 id="credits-h" className="text-[length:var(--t-2xl)]">3D models on this site</h2>
        <p className="max-w-[60ch] text-ink-2">
          The demo listings use real 3D Gaussian splats that people captured and shared on SuperSplat. They were not
          scanned by Mint, and the listing text and prices around them are demo data. Thank you to their authors:
        </p>
        <ul className="grid gap-x-8 gap-y-2 sm:grid-cols-2">
          {credits.map((c) => (
            <li key={c.key} className="text-[15px]">
              <a href={c.url} className="font-semibold text-mint-ink underline-offset-2 hover:underline">
                {c.title}
              </a>{" "}
              by {c.author}, {c.licence}
            </li>
          ))}
        </ul>
      </section>
    </article>
  );
}
