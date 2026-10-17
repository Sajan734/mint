"use client";
import { useEffect, useState } from "react";
import type { Explanation } from "@/lib/types";

const FAKE_MS = 1800;

type Tone = "ok" | "bad" | "unknown";
// Plain-language cues in the buyer agent's sentences. ponytail: keyword match, swap for a typed field if the contract adds one.
export const claimTone = (t: string): Tone =>
  /cannot (check|see|tell)/i.test(t) ? "unknown" : /(can see it|looks the same|matches)/i.test(t) ? "ok" : /(not|missing|different|cannot find)/i.test(t) ? "bad" : "unknown";

/** 1 to 3 filled segments from the "how sure" sentence. */
export const sureLevel = (t: string): number => (/\b(strong|high|clear)\b/i.test(t) ? 3 : /\b(moderate|some|medium)\b/i.test(t) ? 2 : 1);
const SURE_WORD = ["Low", "Moderate", "High"];

const ICON: Record<Tone, { path: string; cls: string; label: string }> = {
  ok: { path: "m5 12 5 5 9-10", cls: "text-mint-ink", label: "Matches" },
  bad: { path: "M6 6l12 12M18 6 6 18", cls: "text-ink", label: "Does not match" },
  unknown: { path: "M6 12h12", cls: "text-ink-2", label: "Could not check" },
};

const Icon = ({ tone }: { tone: Tone }) => (
  <svg aria-hidden viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.75" strokeLinecap="round" strokeLinejoin="round" className={`mt-0.5 shrink-0 ${ICON[tone].cls}`}>
    <path d={ICON[tone].path} />
  </svg>
);

const Block = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="grid gap-2">
    <h4 className="font-semibold">{title}</h4>
    {children}
  </section>
);

export default function VerifyItemPanel({ explanation, verified, onVerify }: {
  explanation: Explanation | null; verified: boolean; onVerify: () => void;
}) {
  const [phase, setPhase] = useState<"idle" | "scanning" | "done">("idle");
  useEffect(() => {
    if (phase !== "scanning") return;
    const t = setTimeout(() => setPhase("done"), FAKE_MS);
    return () => clearTimeout(t);
  }, [phase]);

  const level = explanation ? sureLevel(explanation.how_sure) : 0;
  return (
    <section aria-labelledby="verify-h" className="rounded-lg border border-line bg-surface p-5 md:p-6">
      <h2 id="verify-h" className="text-[length:var(--t-xl)] font-bold">Verify your item</h2>
      <p className="mt-2 max-w-[56ch] text-ink-2">Rescan what you received and Mint compares it with the listing.</p>

      {phase === "idle" && (
        <button type="button" onClick={() => setPhase("scanning")} className="mt-4 min-h-12 rounded-md bg-ink px-6 font-semibold text-bg">
          Start rescan
        </button>
      )}
      {phase !== "idle" && <p className="mt-3 text-sm text-ink-2">Demo only: no camera is used and nothing is uploaded.</p>}
      {phase === "scanning" && (
        <p role="status" className="mt-3 flex items-center gap-2">
          <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-line border-t-ink" />
          Comparing your item with the listing…
        </p>
      )}

      {phase === "done" && !explanation && <p className="mt-3">No result is available right now.</p>}
      {phase === "done" && explanation && (
        <div className="mt-5 grid gap-6">
          <div className="grid gap-3 rounded-md bg-surface-2 p-4">
            <span className="w-fit rounded-sm border border-dashed border-slate px-2 py-0.5 text-sm text-ink-2">Sample result</span>
            <h3 className="text-balance text-[length:var(--t-xl)] font-bold">{explanation.headline}</h3>
            <p className="text-ink-2">{explanation.what_we_compared}</p>
          </div>

          <Block title="What we found">
            <ul className="m-0 grid list-none gap-2 p-0">
              {explanation.what_we_found.map((t, i) => (
                <li key={i} className="flex gap-2"><Icon tone={claimTone(t) === "ok" ? "ok" : "bad"} />{t}</li>
              ))}
            </ul>
          </Block>

          <Block title="How sure we are">
            <div className="flex items-center gap-3">
              <div aria-hidden className="grid w-40 grid-cols-3 gap-1">
                {[1, 2, 3].map((n) => <span key={n} className={`h-2 rounded-full ${n <= level ? "bg-ink" : "bg-line"}`} />)}
              </div>
              <span className="text-sm font-semibold">{SURE_WORD[level - 1]}</span>
            </div>
            <p>{explanation.how_sure}</p>
          </Block>

          <Block title="Listing vs your item">
            <ul className="m-0 grid list-none gap-2 p-0">
              {explanation.listing_vs_item.map((t, i) => {
                const tone = claimTone(t);
                return (
                  <li key={i} className="flex gap-2"><Icon tone={tone} /><span><span className="sr-only">{ICON[tone].label}: </span>{t}</span></li>
                );
              })}
            </ul>
          </Block>

          <Block title="What to do">
            <ol className="m-0 grid list-none gap-3 p-0">
              {explanation.what_to_do.map((t, i) => (
                <li key={i} className="flex gap-3">
                  <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full bg-ink font-mono text-xs text-bg">{i + 1}</span>
                  <span>{t}</span>
                </li>
              ))}
            </ol>
          </Block>

          <Block title="Things to keep in mind">
            <ul className="grid gap-1 pl-5 text-sm text-ink-2" style={{ listStyle: "disc" }}>
              {explanation.caveats.map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          </Block>
          <p className="border-t border-line pt-4 text-sm text-ink-2">{explanation.disclaimer}</p>
        </div>
      )}

      {phase === "done" && (
        verified ? (
          <p className="mt-5 inline-flex items-center gap-2 rounded-md bg-mint-wash px-3 py-2 font-semibold text-mint-ink">
            <svg aria-hidden viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12 5 5 9-10" /></svg>
            Marked as verified.
          </p>
        ) : (
          <button type="button" onClick={onVerify} className="mt-5 min-h-12 rounded-md border border-line px-6 font-semibold hover:border-ink-2">
            Mark as verified
          </button>
        )
      )}
    </section>
  );
}
