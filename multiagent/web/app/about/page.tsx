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
    <article className="mx-auto max-w-[65ch] py-8">
      <h1 className="mb-2 text-[length:var(--t-3xl)] font-bold">How Mint works</h1>
      <p className="mb-6 text-ink-2">Mint helps you see what you are buying before you hand over money.</p>
      <ol className="mb-8 flex list-decimal flex-col gap-3 pl-5">
        {steps.map(([t, d]) => (
          <li key={t}><strong>{t}.</strong> {d}</li>
        ))}
      </ol>
      <h2 className="mb-3 text-xl font-bold">What Mint cannot do</h2>
      <ul className="flex list-disc flex-col gap-2 pl-5">
        {limits.map((l) => <li key={l}>{l}</li>)}
      </ul>
    </article>
  );
}
