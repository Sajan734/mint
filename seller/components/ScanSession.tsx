"use client";

import { createClient } from "@supabase/supabase-js";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { STEPS, phaseOf, splatFraction, stepState } from "@/lib/progress";
import { ANON_KEY, SUPABASE_URL, getPublicJson, listingDocUrl, splatManifestUrl } from "@/lib/supabase";
import type { ListingDoc, SplatManifest, StageEvent } from "@/lib/types";
import Spin from "./Spin";

const POLL_MS = 2000;

type Props = { scanId: string; qrSvg: string; deepLink: string };

/** Waits for the phone: shows the QR code, then live progress, then sends the seller to their draft listing. */
export default function ScanSession({ scanId, qrSvg, deepLink }: Props) {
  const router = useRouter();
  const [stages, setStages] = useState<Record<string, string>>({});
  const [manifest, setManifest] = useState<SplatManifest | null>(null);
  const [listing, setListing] = useState<ListingDoc | null>(null);

  // Live stage events from the splat job (Realtime channel batch:{scanId}). Needs the public anon key; without it
  // the page still works from the polling below, just without the in-between progress.
  useEffect(() => {
    if (!ANON_KEY) return;
    const sb = createClient(SUPABASE_URL, ANON_KEY);
    const channel = sb
      .channel(`batch:${scanId}`)
      .on("broadcast", { event: "stage" }, ({ payload }) => {
        const e = (payload as { payload?: StageEvent }).payload;
        if (e?.stage) setStages((s) => ({ ...s, [e.stage]: e.status }));
      })
      .subscribe();
    return () => {
      void sb.removeChannel(channel);
    };
  }, [scanId]);

  // The published files are the source of truth: the 3D scan's manifest, then the listing document.
  useEffect(() => {
    if (listing) return;
    let stopped = false;
    const tick = async () => {
      const [m, l] = await Promise.all([
        manifest ? Promise.resolve(manifest) : getPublicJson<SplatManifest>(splatManifestUrl(scanId)),
        getPublicJson<ListingDoc>(listingDocUrl(scanId)),
      ]);
      if (stopped) return;
      if (m && !manifest) setManifest(m);
      if (l) setListing(l);
    };
    void tick();
    const timer = setInterval(tick, POLL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [scanId, manifest, listing]);

  const phase = phaseOf({ stages, manifest: !!manifest, listing });

  useEffect(() => {
    if (phase !== "listed") return;
    const t = setTimeout(() => router.push(`/listing/${scanId}`), 1500);
    return () => clearTimeout(t);
  }, [phase, router, scanId]);

  const fraction = splatFraction(stages);
  return (
    <div className="grid items-start gap-8 md:grid-cols-2">
      <section className="pad grid aspect-square place-items-center rounded-lg border border-line p-6">
        {manifest?.spin_urls?.length ? (
          <Spin frames={manifest.spin_urls} alt="Your 3D scan" />
        ) : phase === "waiting" ? (
          <div className="flex flex-col items-center gap-4 text-center">
            <div
              className="w-60 rounded-md bg-white p-3"
              role="img"
              aria-label="QR code that opens the Mint app for this scan"
              dangerouslySetInnerHTML={{ __html: qrSvg }}
            />
            <p className="max-w-xs text-sm text-ink-2">Open your iPhone camera and point it at the code.</p>
            <a href={deepLink} className="btn-secondary text-sm">
              On your iPhone? Open the Mint app
            </a>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 text-center" aria-live="polite">
            <span className="size-10 animate-spin rounded-full border-4 border-line border-t-mint" aria-hidden />
            <p className="font-medium">Building your 3D scan</p>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-6">
        <ol className="flex flex-col gap-4" aria-label="Progress">
          {STEPS.map((step, n) => {
            const state = stepState(step.phase, phase);
            return (
              <li key={step.phase} className="flex gap-3" aria-current={state === "active" ? "step" : undefined}>
                <span
                  className={`grid size-8 shrink-0 place-items-center rounded-full border text-sm font-semibold ${
                    state === "done" ? "border-mint bg-mint text-[#0b0f0e]" : state === "active" ? "border-ink" : "border-line text-ink-2"
                  }`}
                >
                  {state === "done" ? "✓" : n + 1}
                </span>
                <div className="flex-1">
                  <p className={state === "todo" ? "text-ink-2" : "font-semibold"}>{step.label}</p>
                  <p className="text-sm text-ink-2">{step.hint}</p>
                  {step.phase === "scanning" && state === "active" && fraction > 0 && (
                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden>
                      <div className="h-full bg-mint transition-all" style={{ width: `${Math.round(fraction * 100)}%` }} />
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>

        {phase === "rejected" && (
          <p role="alert" className="rounded-md border border-amber bg-surface p-4 text-sm">
            {listing?.rejection?.match_check.reason ?? "This scan doesn't look like a product we can list."}{" "}
            <Link href="/scan/new" className="underline">Scan again</Link>
          </p>
        )}
        {phase === "failed" && (
          <p role="alert" className="rounded-md border border-coral bg-surface p-4 text-sm">
            We couldn&apos;t write this listing ({listing?.error ?? "unknown error"}).{" "}
            <Link href="/scan/new" className="underline">Scan again</Link>
          </p>
        )}
        {phase === "listed" && (
          <Link href={`/listing/${scanId}`} className="btn-primary self-start">
            Review your listing
          </Link>
        )}
        <p className="font-mono text-xs text-ink-2">scan {scanId}</p>
      </section>
    </div>
  );
}
