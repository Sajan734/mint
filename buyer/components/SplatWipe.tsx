"use client";
// True 3D before/after: the listing's splat under the buyer's splat, the top one clipped at the wipe line.
// One shared camera pose, so turning either scan turns both. Only shown when both splat URLs exist (never in mock today).
import { useRef, useState } from "react";
import SplatViewer, { type CameraPose } from "@/components/SplatViewer";

const tag = "pointer-events-none absolute top-2 z-10 rounded-sm bg-surface px-2 py-0.5 text-xs font-semibold text-ink shadow-sm";

export default function SplatWipe({ listingSrc, buyerSrc }: { listingSrc: string; buyerSrc: string }) {
  const pose = useRef<CameraPose>({ azimuth: 0, polar: 0, distance: 0 }); // distance 0 = the first viewer frames it
  const [pct, setPct] = useState(50);
  return (
    <section aria-labelledby="splat-wipe-h" className="flex flex-col gap-3">
      <h2 id="splat-wipe-h" className="text-[length:var(--t-lg)] font-bold">Both scans in 3D</h2>
      <div className="relative aspect-square w-full overflow-hidden rounded-lg bg-surface-2">
        <div className="absolute inset-0">
          <SplatViewer src={listingSrc} label="The listing's 3D scan" interactive autoRotate={false} sharedPose={pose} />
        </div>
        {/* clip-path also clips hit-testing, so a drag left of the line turns the listing scan, right of it yours */}
        <div data-testid="splat-wipe-top" className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${pct}%)` }}>
          <SplatViewer src={buyerSrc} label="Your 3D scan" interactive autoRotate={false} sharedPose={pose} />
        </div>
        <div aria-hidden className="pointer-events-none absolute inset-y-0 z-10 w-0.5 -translate-x-1/2 bg-mint" style={{ left: `${pct}%` }} />
        <span className={`${tag} left-2`}>Listing</span>
        <span className={`${tag} right-2`}>Your scan</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={pct}
        onChange={(e) => setPct(Number(e.target.value))}
        aria-label="Compare the listing's 3D scan with yours"
        aria-valuetext={`${pct}% listing, ${100 - pct}% your scan`}
        className="h-11 w-full accent-[var(--mint-ink)]"
      />
      <p className="text-sm text-ink-2">Drag a scan to turn both together. Move the slider to wipe between them.</p>
    </section>
  );
}
