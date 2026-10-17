"use client";
import { useEffect, useState } from "react";
import type { Explanation } from "@/lib/types";

const FAKE_MS = 1800;
const List = ({ items, ordered }: { items: string[]; ordered?: boolean }) => {
  const Tag = ordered ? "ol" : "ul";
  return <Tag className={`mt-2 grid gap-1 pl-5 ${ordered ? "list-decimal" : "list-disc"}`}>{items.map((t, i) => <li key={i}>{t}</li>)}</Tag>;
};

export default function VerifyItemPanel({ explanation, verified, onVerify }: {
  explanation: Explanation | null; verified: boolean; onVerify: () => void;
}) {
  const [phase, setPhase] = useState<"idle" | "scanning" | "done">("idle");
  useEffect(() => {
    if (phase !== "scanning") return;
    const t = setTimeout(() => setPhase("done"), FAKE_MS);
    return () => clearTimeout(t);
  }, [phase]);

  return (
    <section aria-labelledby="verify-h" className="rounded-md border border-line bg-surface p-4">
      <h2 id="verify-h" className="text-[length:var(--t-xl)] font-bold">Verify your item</h2>
      <p className="mt-2 text-ink-2">Rescan what you received and Mint compares it with the listing.</p>

      {phase === "idle" && (
        <button type="button" onClick={() => setPhase("scanning")} className="mt-4 min-h-11 rounded-md bg-ink px-5 text-bg">
          Start rescan
        </button>
      )}
      {phase !== "idle" && <p className="mt-3 text-sm text-ink-2">Demo only: no camera is used and nothing is uploaded.</p>}
      {phase === "scanning" && <p role="status" className="mt-3">Comparing your item with the listing…</p>}

      {phase === "done" && !explanation && <p className="mt-3">No result is available right now.</p>}
      {phase === "done" && explanation && (
        <div className="mt-4 grid gap-4">
          <span className="w-fit rounded-sm border border-dashed border-slate px-2 py-0.5 text-sm text-ink-2">Sample result</span>
          <h3 className="text-[length:var(--t-lg)] font-bold">{explanation.headline}</h3>
          <p>{explanation.what_we_compared}</p>
          <div><h4 className="font-semibold">What we found</h4><List items={explanation.what_we_found} /></div>
          <p><strong>How sure we are: </strong>{explanation.how_sure}</p>
          <div><h4 className="font-semibold">Listing vs your item</h4><List items={explanation.listing_vs_item} /></div>
          <div><h4 className="font-semibold">What to do</h4><List items={explanation.what_to_do} ordered /></div>
          <div><h4 className="font-semibold">Things to keep in mind</h4><List items={explanation.caveats} /></div>
          <p className="text-sm text-ink-2">{explanation.disclaimer}</p>
        </div>
      )}

      {phase === "done" && (
        verified ? (
          <p className="mt-4 font-semibold">Marked as verified.</p>
        ) : (
          <button type="button" onClick={onVerify} className="mt-4 min-h-11 rounded-md border border-line px-5 hover:border-ink-2">
            Mark as verified
          </button>
        )
      )}
    </section>
  );
}
