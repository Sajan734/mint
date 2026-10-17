"use client";
// The listing card's root and image box, with hover-to-3D. It renders the card's <article> so hover and focus anywhere
// on the card count: the title link's `after:inset-0` overlay covers the image and would swallow pointer events there.
// Static photo first. After a short dwell (fine pointer hover, or keyboard focus) it mounts the splat spinning, or the
// frame spinner when there is no splat. Touch and reduced motion: static only.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { MarketListing } from "@/lib/types";
import SplatViewer, { preloadSplatScene } from "./SplatViewer";
import SpinViewer from "./SpinViewer";

const DWELL_MS = 200;
const MIN_SPIN_FRAMES = 8;

const canPlay = () =>
  typeof window !== "undefined" &&
  !!window.matchMedia?.("(hover: hover) and (pointer: fine)").matches &&
  !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const PILL = "pointer-events-none absolute bottom-2.5 left-2.5 rounded-full bg-raised px-2.5 py-1 text-[13px] font-semibold leading-none text-ink";

export default function CardMedia({
  item,
  className,
  children,
}: {
  item: MarketListing;
  className?: string;
  children: ReactNode;
}) {
  const { listing: l } = item;
  // The first spin frame stands on the shelf (transparent background); preview renders can carry a flat grey backdrop.
  const still = item.frames[0] ?? l.preview_images[0];
  const splat = item.splat_url;
  const canSpin = item.frames.length >= MIN_SPIN_FRAMES;
  const [active, setActive] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    if (splat && canPlay()) preloadSplatScene();
  }, [splat]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const start = () => {
    if (!canPlay() || (!splat && !canSpin)) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setActive(true), DWELL_MS);
  };
  const stop = () => {
    clearTimeout(timer.current);
    setActive(false);
  };

  const showSplat = active && !!splat && !failed;
  const showSpin = active && !showSplat && canSpin;
  return (
    <article
      className={className}
      onPointerEnter={(e) => { if (e.pointerType === "mouse") start(); }}
      onPointerLeave={stop}
      onFocus={start}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) stop(); }}
    >
      <div
        className={`relative aspect-square overflow-hidden rounded-[16px] bg-surface transition-colors duration-200 group-hover:bg-surface-2 ${item.status === "available" ? "" : "opacity-60"}`}
      >
        {still && (
          // eslint-disable-next-line @next/next/no-img-element -- scan frames come from storage or /public
          <img src={still} alt="" draggable={false} className="h-full w-full object-contain p-[6%] transition-transform duration-500 ease-[var(--ease)] group-hover:scale-[1.04] motion-reduce:group-hover:scale-100" />
        )}
        {showSplat && (
          <div className="absolute inset-0">
            <SplatViewer
              src={splat}
              label={`3D view of ${l.title}`}
              poster={still}
              autoRotate
              className="bg-surface-2"
              onError={() => setFailed(true)}
            />
          </div>
        )}
        {showSpin && (
          <div className="absolute inset-0">
            <SpinViewer frames={item.frames} alt={l.title} variant="card" />
          </div>
        )}
        {item.splat_url && <span className={PILL}>3D</span>}
      </div>
      {children}
    </article>
  );
}
