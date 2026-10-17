"use client";
// Buyer rescan for one listing: the phone hand-off (ScanFlow, kind "verify") until it reports ready, then the
// result on the same URL. In demo mode ScanFlow replays a real recorded CompareResponse picked for this listing.
import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import ScanFlow from "@/components/ScanFlow";
import CompareResult from "@/components/CompareResult";
import type { CompareResponse } from "@/lib/compare-types";
import type { ScanState } from "@/lib/scan-feed";
import { fetchBuyerSplat, mockRun, pickRun } from "@/lib/compare";
import { useLocalListings } from "@/lib/local-listings";
import { useMockMode } from "@/lib/mock-mode";

export interface CheckListing {
  title: string;
  frames: string[];
  splatUrl: string | null;
}
export interface CheckFlowProps {
  listingId: string;
  cid: string;
  deepLink: string;
  qrSvg: string;
  listing: CheckListing | null; // null: not on the server, so look in this browser's store
}

const noSub = () => () => {};
const useHydrated = () => useSyncExternalStore(noSub, () => true, () => false);

export default function CheckFlow({ listingId, cid, deepLink, qrSvg, listing }: CheckFlowProps) {
  const local = useLocalListings().find((l) => l.id === listingId);
  const hydrated = useHydrated();
  const mock = useMockMode();
  const [done, setDone] = useState<{ result: CompareResponse; recorded: boolean } | null>(null);
  const [buyerSplat, setBuyerSplat] = useState<string | null>(null);

  const info: CheckListing | null =
    listing ?? (local ? { title: local.market.listing.title, frames: local.market.frames, splatUrl: local.market.splat_url } : null);

  if (!info) {
    if (!hydrated) return null; // the browser store is not read yet
    return (
      <div className="flex max-w-xl flex-col items-start gap-4 py-10">
        <h1 className="text-[length:var(--t-2xl)] font-bold">This listing was published on another device.</h1>
        <Link href="/" className="btn-secondary">Back to Mint</Link>
      </div>
    );
  }

  const { run, note } = pickRun(listingId, info.frames);
  const onDone = (s: ScanState) => {
    if (!s.compare) return;
    setDone({ result: s.compare, recorded: mock });
    if (!mock) void fetchBuyerSplat(cid).then(setBuyerSplat);
  };

  return (
    <div className="flex flex-col gap-6">
      <Link href={`/listing/${listingId}`} className="inline-flex min-h-11 w-fit max-w-full items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
        <svg aria-hidden viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0"><path d="m15 6-6 6 6 6" /></svg>
        <span className="truncate">Back to {info.title}</span>
      </Link>
      {done ? (
        <CompareResult
          result={done.result}
          listingId={listingId}
          recorded={done.recorded}
          note={done.recorded ? note : null}
          splats={info.splatUrl && buyerSplat ? { listing: info.splatUrl, buyer: buyerSplat } : null}
        />
      ) : (
        <>
          <header className="flex max-w-2xl flex-col gap-2">
            <h1 className="text-[length:var(--t-2xl)] font-bold">Scan the item you got</h1>
            <p className="text-ink-2">
              Scan the code with your iPhone and walk slowly around the item. Mint compares your scan with the
              seller&apos;s and shows what matches.
            </p>
          </header>
          <ScanFlow kind="verify" scanId={cid} listingId={listingId} deepLink={deepLink} qrSvg={qrSvg} mockResult={mockRun(run)} onDone={onDone} />
        </>
      )}
    </div>
  );
}
