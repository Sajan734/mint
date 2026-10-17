// Twin: buyer/components/ScanFlow.tsx (keep identical)
"use client";
// The phone hand-off for a listing scan or a buyer's check (PLAN_UX 2.3). Left: what the phone is doing, in the
// iOS app's look (scanner/ios/Mint/Screens.swift). Right: the steps. All signals come from lib/scan-feed.ts.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { CompareResponse } from "@/lib/compare-types";
import { getLocal, upsertLocal } from "@/lib/local-listings";
import { isMockMode, useMockMode } from "@/lib/mock-mode";
import { STEPS, stepMark, type ScanKind, type StepMark } from "@/lib/progress";
import { initialScan, isFinal, watchScan, type FeedState, type ScanState } from "@/lib/scan-feed";
import type { MarketListing } from "@/lib/types";
import PhoneRing, { ROUNDED } from "./PhoneRing";

export interface ScanFlowProps {
  kind: ScanKind;
  scanId: string;
  listingId?: string;
  deepLink: string; // mint://scan?id=... or mint://verify?id=...&listing=...
  qrSvg: string; // inline SVG markup of the QR for deepLink
  /** Demo mode replays this: a MarketListing (listing) or a CompareResponse (verify). */
  mockResult?: MarketListing | CompareResponse;
  /** Called once when the scan ends (ready, rejected or failed). */
  onDone?: (s: ScanState) => void;
}

const MINT_BTN = "inline-flex min-h-11 items-center justify-center rounded-md bg-mint px-5 font-bold text-[#0b0f0e] hover:opacity-90";
const LINE_BTN = "inline-flex min-h-11 items-center justify-center rounded-md border border-white/30 px-5 text-sm font-semibold text-white hover:border-white";
const rounded = { fontFamily: ROUNDED };
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "es"}`;

/** The panel's words for a state: [title, line under it]. Also what the live region reads out. */
function headline(s: FeedState): [string, string | null] {
  const listing = s.kind === "listing";
  switch (s.phase) {
    case "waiting":
      return ["Scan this code with your iPhone", "Use the Camera app, or the Mint app's own scanner."];
    case "connected":
      return ["Phone connected", "Turn the item slowly."];
    case "uploading":
      return ["Uploading your scan…", s.passes ? `${plural(s.passes, "pass")} · keep the app open` : "Keep the app open"];
    case "processing": {
      const title = STEPS[s.kind][3].label;
      return [title, s.subStep && s.subStep !== title ? `${s.subStep}…` : null];
    }
    case "ready":
      return listing ? ["Your listing is ready", "Opening the editor…"] : ["Your phone is done", null];
    case "rejected":
      return [listing ? "We cannot list this one" : "We cannot check this scan", s.message];
    case "failed":
      return ["Something went wrong on our side", null];
    case "cancelled":
      return ["Scan cancelled on your phone", "Scan again when you are ready."];
  }
}

/**
 * Rings rippling out to the edge of their box, as in Screens.swift Ripples: 3 thin mint rings a third of a cycle
 * apart, each growing linearly over 2.4 s from `from` (a fraction of the box) and fading from 50% to nothing. The box
 * is part of the layout, so the rings never cross the text. Hidden with reduced motion.
 */
function Ripples({ from }: { from: number }) {
  return (
    <span aria-hidden className="pointer-events-none absolute inset-0 motion-reduce:hidden">
      {[0, 0.8, 1.6].map((d) => (
        <span
          key={d}
          className="animate-mint-ripple absolute inset-0 rounded-full border-[1.5px] border-mint opacity-0"
          style={{ ["--ripple-from" as string]: from, animationDelay: `${-d}s` }}
        />
      ))}
    </span>
  );
}

const Check = ({ className }: { className: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
);
const Cross = ({ className }: { className: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden>
    <path d="M7 7l10 10M17 7L7 17" />
  </svg>
);
const PhoneGlyph = () => (
  <svg viewBox="0 0 24 24" className="h-14 w-14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden>
    <rect x="6.5" y="2.5" width="11" height="19" rx="2.5" />
    <path d="M10.5 5h3" />
    <circle cx="12" cy="18.2" r="0.6" fill="currentColor" />
  </svg>
);

/** The scan's own spin frames while the listing is written (assets/splats/{id}.json spin_urls). */
function Frames({ frames, onFail }: { frames: string[]; onFail: () => void }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    frames.forEach((src) => {
      new Image().src = src; // preload so turning never flickers
    });
    if (frames.length < 2 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setInterval(() => setI((v) => (v + 1) % frames.length), 140);
    return () => clearInterval(t);
  }, [frames]);
  return (
    // eslint-disable-next-line @next/next/no-img-element -- frames from Storage or the demo folder
    <img src={frames[i % frames.length]} alt="Your scan, turning" onError={onFail} className="aspect-square w-full max-w-64 rounded-md object-cover" />
  );
}

function Panel({ s, deepLink, qrSvg, scanId, listingId }: { s: FeedState; deepLink: string; qrSvg: string; scanId: string; listingId?: string }) {
  const [framesFailed, setFramesFailed] = useState(false);
  const [title, line] = headline(s);
  const again = s.kind === "listing" ? "/sell/scan/new" : listingId ? `/listing/${listingId}/check` : "/";
  const heading = (
    <div>
      <p className="text-2xl font-extrabold leading-tight" style={rounded}>{title}</p>
      {line && <p className="mt-1.5 text-white/75">{line}</p>}
    </div>
  );

  let body;
  if (s.phase === "waiting") {
    body = (
      <>
        <div className="relative grid size-72 place-items-center md:size-80">
          <Ripples from={0.7} />
          <div
            className="relative w-52 rounded-md bg-white p-3 md:w-56"
            role="img"
            aria-label="QR code that opens the Mint app for this scan"
            dangerouslySetInnerHTML={{ __html: qrSvg }}
          />
        </div>
        {heading}
        <a href={deepLink} className={LINE_BTN}>On your iPhone? Open the Mint app</a>
      </>
    );
  } else if (s.phase === "connected") {
    body = (
      <>
        <span className="grid size-28 place-items-center rounded-full bg-mint/15 text-mint"><PhoneGlyph /></span>
        {heading}
        {s.passes > 0 && <p className="rounded-full bg-white/10 px-3 py-1 text-sm font-semibold">{plural(s.passes, "pass")} recorded</p>}
      </>
    );
  } else if (s.phase === "uploading") {
    body = (
      <>
        <PhoneRing pct={s.uploadPct ?? 0} />
        {heading}
      </>
    );
  } else if (s.phase === "processing") {
    body = (
      <>
        {s.spinUrls?.length && !framesFailed ? (
          <Frames frames={s.spinUrls} onFail={() => setFramesFailed(true)} />
        ) : (
          <span className="size-14 animate-spin rounded-full border-4 border-white/15 border-t-mint motion-reduce:animate-none" aria-hidden />
        )}
        {heading}
        {s.message && <p className="max-w-sm rounded-md bg-white/10 px-4 py-3 text-sm">{s.message}</p>}
      </>
    );
  } else if (s.phase === "ready") {
    body = (
      <>
        <span className="relative grid size-72 place-items-center">
          <Ripples from={0.31} />
          <span className="relative grid size-28 place-items-center rounded-full bg-mint text-[#0b0f0e] shadow-[0_0_30px_rgb(61_220_151/0.55)]">
            <Check className="size-12" />
          </span>
        </span>
        {s.kind === "listing" && <p className="font-semibold text-mint" style={rounded}>Your phone is done</p>}
        {heading}
        {s.kind === "listing" && <Link href={`/listing/${scanId}`} className={MINT_BTN}>Review your listing</Link>}
      </>
    );
  } else {
    body = (
      <>
        <span className="grid size-20 place-items-center rounded-full bg-coral text-[#0b0f0e]"><Cross className="size-9" /></span>
        {heading}
        {s.phase === "failed" && s.message && (
          <details className="max-w-sm text-left text-xs text-white/65">
            <summary className="cursor-pointer">Details</summary>
            <p className="mt-1 break-words font-mono">{s.message}</p>
          </details>
        )}
        <a href={again} className={MINT_BTN}>Scan again</a>
      </>
    );
  }

  return (
    <section
      aria-label="Your phone"
      className="grid min-h-[26rem] place-items-center overflow-hidden rounded-lg border border-line bg-[#0b0f0e] p-6 text-white md:aspect-square"
    >
      <div className="flex w-full max-w-sm flex-col items-center gap-5 text-center">{body}</div>
    </section>
  );
}

const WORD: Record<StepMark, string> = { done: "Done", active: "Now", todo: "Not started", stopped: "Stopped" };

function MarkIcon({ mark, n }: { mark: StepMark; n: number }) {
  const base = "grid size-8 shrink-0 place-items-center rounded-full text-sm font-semibold";
  if (mark === "done") return <span className={`${base} bg-mint text-[#0b0f0e]`}><Check className="size-4" /></span>;
  if (mark === "stopped") return <span className={`${base} bg-coral text-[#0b0f0e]`}><Cross className="size-4" /></span>;
  if (mark === "active")
    return (
      <span className={`${base} border-2 border-ink`}>
        <span className="size-2.5 animate-pulse rounded-full bg-mint motion-reduce:animate-none" />
      </span>
    );
  return <span className={`${base} border border-line text-ink-2`}>{n}</span>;
}

function Steps({ s }: { s: FeedState }) {
  return (
    <ol aria-label="Progress" className="flex flex-col">
      {STEPS[s.kind].map((step, i) => {
        const mark = stepMark(step.id, s.phase);
        const detail =
          step.id === "connected" && mark !== "todo" && s.passes > 0
            ? `${plural(s.passes, "pass")} recorded`
            : step.id === "uploading" && mark === "active"
              ? `${s.uploadPct ?? 0}%`
              : step.id === "processing" && mark === "active" && s.subStep
                ? s.subStep
                : step.hint;
        return (
          <li key={step.id} className="flex gap-3 py-2.5" aria-current={mark === "active" ? "step" : undefined}>
            <MarkIcon mark={mark} n={i + 1} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-3">
                <p className={mark === "todo" ? "text-ink-2" : "font-semibold"}>{step.label}</p>
                <span className={`shrink-0 text-xs font-semibold ${mark === "todo" ? "sr-only" : mark === "done" ? "text-mint-ink" : "text-ink"}`}>
                  {WORD[mark]}
                </span>
              </div>
              <p className="text-sm text-ink-2">{detail}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** A listing that just finished becomes a draft on this device, so the editor opens it (lib/local-listings). */
function saveDraft(id: string, market: MarketListing, mock: boolean) {
  if (getLocal(id)) return; // never overwrite the seller's edits
  const now = new Date().toISOString();
  upsertLocal({ id, state: "draft", source: mock ? "mock" : "live", suggested_price_cad: market.listing.price_cad, market, created_at: now, updated_at: now });
}

export default function ScanFlow({ kind, scanId, listingId, deepLink, qrSvg, mockResult, onDone }: ScanFlowProps) {
  const router = useRouter();
  const mock = useMockMode();
  const [skip, setSkip] = useState(false);
  const [s, setS] = useState<FeedState>(() => initialScan(kind, true, 0));
  const latest = useRef({ mockResult, onDone });
  useEffect(() => {
    latest.current = { mockResult, onDone };
  });

  useEffect(() => {
    const outcome = new URLSearchParams(window.location.search).get("outcome");
    // isMockMode(), not the hook value: on the first effect after hydration the hook still reports the server's false.
    return watchScan(
      {
        scanId,
        kind,
        listingId,
        mock: isMockMode(),
        mockResult: latest.current.mockResult,
        outcome: outcome === "rejected" || outcome === "failed" ? outcome : undefined,
        skip,
      },
      setS,
    );
  }, [scanId, kind, listingId, mock, skip]);

  useEffect(() => {
    if (!isFinal(s.phase)) return;
    latest.current.onDone?.(s);
    if (kind !== "listing" || s.phase !== "ready") return;
    const market = s.listing?.market_listing;
    if (market) saveDraft(scanId, market, !s.live);
    const t = setTimeout(() => router.push(`/listing/${scanId}`), 1500);
    return () => clearTimeout(t);
  }, [s, kind, scanId, router]);

  const [title, line] = headline(s);
  return (
    <div className="flex flex-col gap-4">
      {mock && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-mint-wash px-4 py-2.5 text-sm text-ink">
          <p>
            <span className="font-semibold">Demo:</span> no phone needed. This replays a recorded result.
          </p>
          {!isFinal(s.phase) && (
            <button type="button" onClick={() => setSkip(true)} className="btn-secondary min-h-11 px-4 text-sm">
              Skip to result
            </button>
          )}
        </div>
      )}
      <div className="grid items-start gap-6 md:grid-cols-2 md:gap-8">
        <Panel s={s} deepLink={deepLink} qrSvg={qrSvg} scanId={scanId} listingId={listingId} />
        <section aria-label="Steps" className="flex flex-col gap-4">
          <Steps s={s} />
          {s.hint && (
            <p className="rounded-md border border-line bg-surface p-3 text-sm" role="status">
              {s.hint}
            </p>
          )}
          <p className="font-mono text-xs text-ink-2">scan {scanId}</p>
          <p className="sr-only" aria-live="polite">
            {line && s.phase !== "uploading" ? `${title}. ${line}` : title}
          </p>
        </section>
      </div>
    </div>
  );
}
export { ScanFlow };
