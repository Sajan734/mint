"use client";
// "How it matches": the buyer agent's CompareResponse in plain words (PLAN_UX section 4). Scores and probabilities
// are never shown as numbers; only counts of views are.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { ClaimsFinding, CompareResponse, VerdictLabel } from "@/lib/compare-types";
import { CATEGORY_WORDS, CLAIM_WORDS, causeLine, heading, runFooter } from "@/lib/compare";
import SplatWipe from "@/components/SplatWipe";

export interface CompareResultProps {
  result: CompareResponse;
  listingId: string;
  recorded?: boolean; // a replayed demo run: footer pill + run line
  note?: string | null; // e.g. the recorded run is from another item
  splats?: { listing: string; buyer: string } | null; // both 3D scans exist: show the 3D wipe too
}

type Mark = "check" | "cross" | "dash";
const PATHS: Record<Mark, string> = { check: "m5 12 5 5 9-10", cross: "M6 6l12 12M18 6 6 18", dash: "M6 12h12" };
const Icon = ({ mark, className }: { mark: Mark; className: string }) => (
  <svg aria-hidden data-icon={mark} viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.75" strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 ${className}`}>
    <path d={PATHS[mark]} />
  </svg>
);
const CLAIM_MARK: Record<ClaimsFinding["status"], { mark: Mark; cls: string }> = {
  supported: { mark: "check", cls: "text-mint-ink" },
  contradicted: { mark: "cross", cls: "text-ink" },
  unverifiable: { mark: "dash", cls: "text-ink-2" },
};
// Binary: a match is a check, anything else a cross. A failed check has no verdict and shows no mark at all.
const VERDICT_MARK = (label: VerdictLabel | undefined): { mark: Mark; cls: string } =>
  label === "same" ? { mark: "check", cls: "bg-mint-wash text-mint-ink" } : { mark: "cross", cls: "bg-coral-wash text-ink" };

const h2 = "text-[length:var(--t-xl)]";

export default function CompareResult({ result, listingId, recorded = false, note = null, splats = null }: CompareResultProps) {
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => title.current?.focus(), []); // the scan flow just swapped out: move focus to the answer
  useEffect(() => {
    if (copy !== "copied") return;
    const t = setTimeout(() => setCopy("idle"), 2000);
    return () => clearTimeout(t);
  }, [copy]);

  const v = result.status === "done" ? result.verdict : null;
  const ev = v?.evidence;
  const ns = result.next_step;
  const caveats = v?.caveats ?? [];
  const disclaimer = result.explanation?.disclaimer;
  const mark = VERDICT_MARK(v?.label);
  const cause = causeLine(result);

  const copyMessage = (text: string) =>
    navigator.clipboard?.writeText(text).then(() => setCopy("copied"), () => setCopy("failed")) ?? setCopy("failed");

  return (
    <article aria-labelledby="result-h" className="flex flex-col gap-8">
      <header className="flex max-w-3xl flex-col gap-3">
        {/* Focus lands here for screen readers; it is not a control, so no ring (inline: the global :focus-visible rule is unlayered) */}
        <h1 id="result-h" ref={title} tabIndex={-1} style={{ outline: "none" }} className="flex items-center gap-3 text-[2rem] md:text-[2.5rem]">
          {v && (
            <span className={`flex size-10 shrink-0 items-center justify-center rounded-full ${mark.cls}`}>
              <Icon mark={mark.mark} className="" />
            </span>
          )}
          {heading(result)}
        </h1>
        {cause && <p className="text-[length:var(--t-lg)]">{cause}</p>}
        {note && (
          <p role="note" className="w-fit rounded-full bg-amber-wash px-4 py-1.5 text-sm font-medium text-amber">
            {note}
          </p>
        )}
        {!v ? (
          <>
            <p>{result.error?.message ?? "Something went wrong on our side."}</p>
            <a href={`/listing/${listingId}/check`} className="btn-primary w-fit">Try again</a>
          </>
        ) : (
          <>
            {result.explanation?.how_sure && <p className="text-[length:var(--t-lg)]">{result.explanation.how_sure}</p>}
            <p className="flex flex-wrap gap-x-2 text-sm text-ink-2">
              <span className="font-semibold text-ink">Compared:</span>
              <span>{`${ev!.usable_views} usable views of ${ev!.requested_views}`}</span>
              {ev!.failed_views.length > 0 && <span>· <span>{`${ev!.failed_views.length} failed`}</span></span>}
            </p>
          </>
        )}
      </header>

      {v && ev && (
        <div className="grid grid-cols-1 gap-8 md:grid-cols-12 md:gap-10">
          {splats && (
            <div className="min-w-0 md:sticky md:top-24 md:col-span-7 md:self-start">
              <SplatWipe listingSrc={splats.listing} buyerSrc={splats.buyer} />
            </div>
          )}

          <div className={`flex min-w-0 flex-col gap-8 ${splats ? "md:col-span-5" : "md:col-span-12 md:max-w-3xl"}`}>
            <section aria-labelledby="diff-h" className="flex flex-col gap-2">
              <h2 id="diff-h" className={h2}>What looks different</h2>
              {ev.flagged.length === 0 ? (
                <p className="text-ink-2">Nothing was flagged.</p>
              ) : (
                <ul className="m-0 flex list-none flex-col p-0">
                  {ev.flagged.map((c) => {
                    const views = ev.categories[c]?.views ?? [];
                    return (
                      <li key={c} className="flex flex-col gap-2 py-3">
                        <p className="flex items-start gap-2">
                          <span aria-hidden className="mt-2 size-2 shrink-0 rounded-full bg-coral" />
                          <span>
                            <span className="font-semibold">{CATEGORY_WORDS[c]}</span>{" "}
                            <span className="text-ink-2">{`in ${views.length} of ${ev.usable_views} views`}</span>
                          </span>
                        </p>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            <section aria-labelledby="claims-h" className="flex flex-col gap-2">
              <h2 id="claims-h" className={h2}>What the listing says</h2>
              {!result.claims_available || result.claims_findings.length === 0 ? (
                <p className="text-ink-2">The listing has no claims to check.</p>
              ) : (
                <ul className="m-0 flex list-none flex-col p-0">
                  {result.claims_findings.map((f, k) => (
                    <li key={k} data-status={f.status} className="flex flex-col gap-1.5 py-3">
                      <p className="font-semibold">{f.claim}</p>
                      <p className="flex items-center gap-1.5 text-sm">
                        <Icon mark={CLAIM_MARK[f.status].mark} className={CLAIM_MARK[f.status].cls} />
                        {CLAIM_WORDS[f.status]}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {ns && (
              <section aria-labelledby="next-h" className="flex flex-col gap-3 rounded-lg bg-surface p-4">
                <h2 id="next-h" className={h2}>Next step</h2>
                <p>{ns.summary}</p>
                {ns.message_to_seller && (
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold">Message to the seller</h3>
                      {!ns.is_template && (
                        <span className="rounded-full bg-surface px-3 py-0.5 text-sm text-ink-2">Drafted by AI</span>
                      )}
                    </div>
                    <p className="rounded-md bg-surface-2 p-3 text-sm">{ns.message_to_seller}</p>
                  </div>
                )}
                <div className="flex flex-wrap gap-3">
                  {ns.message_to_seller && (
                    <button type="button" className="btn-secondary" onClick={() => copyMessage(ns.message_to_seller!)}>
                      {copy === "copied" ? "Copied" : "Copy message"}
                    </button>
                  )}
                  <Link href={`/listing/${listingId}#contact`} className="btn-primary">Contact seller</Link>
                </div>
                <p role="status" className="text-sm text-ink-2 empty:hidden">
                  {copy === "failed" ? "Copy did not work. Select the message and copy it." : ""}
                </p>
              </section>
            )}
          </div>
        </div>
      )}

      {(caveats.length > 0 || disclaimer || recorded) && (
        <footer className="flex flex-col gap-3 pt-6 text-sm text-ink-2">
          {caveats.length > 0 && (
            <ul className="m-0 flex list-disc flex-col gap-1 pl-5">
              {caveats.map((c) => <li key={c}>{c}</li>)}
            </ul>
          )}
          {disclaimer && <p>{disclaimer}</p>}
          {recorded && (
            <p className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-amber-wash px-3 py-0.5 text-sm font-semibold text-amber">Recorded result</span>
              <span className="tabular-nums text-sm">{runFooter(result)}</span>
            </p>
          )}
        </footer>
      )}
    </article>
  );
}
