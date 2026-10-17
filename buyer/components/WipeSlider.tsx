"use client";
// Before/after image wipe over the real view pairs the buyer agent compared: "Listing" (a_NN) on the left,
// "Your scan" (b_NN) on the right. Drag anywhere on the photo, or use the native range input (arrows, Home, End).
import { useEffect, useRef, useState, type PointerEvent } from "react";
import type { EvidenceCategory } from "@/lib/compare-types";
import { CATEGORY_WORDS, pairSrc, viewLabel, viewName } from "@/lib/compare";

export interface WipeSliderProps {
  run8: string; // folder under /local/compare/
  count: number; // pairs 0..count-1
  index: number; // the pair on show
  onIndex: (i: number) => void;
  flagged: ReadonlyMap<number, readonly EvidenceCategory[]>;
}

const img = "absolute inset-0 h-full w-full object-contain";
const tag = "pointer-events-none absolute top-2 rounded-sm bg-surface px-2 py-0.5 text-xs font-semibold text-ink shadow-sm";

export default function WipeSlider({ run8, count, index, onIndex, flagged }: WipeSliderProps) {
  const [pct, setPct] = useState(50);
  const [missing, setMissing] = useState(false);
  const dragging = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  const strip = useRef<HTMLUListElement>(null);

  // Keep the chosen thumbnail visible in the phone's scrolling strip, without scrolling the page.
  useEffect(() => {
    const s = strip.current;
    const b = s?.children[index] as HTMLElement | undefined;
    if (s && b) s.scrollLeft = b.offsetLeft - s.clientWidth / 2 + b.clientWidth / 2;
  }, [index]);

  if (missing)
    return (
      <p role="note" className="rounded-lg border border-dashed border-line-strong bg-surface-2 p-5 text-sm text-ink-2">
        Comparison photos are not on this machine. Run python buyer/scripts/make_demo_assets.py.
      </p>
    );

  const name = viewName(viewLabel(index));
  const cats = flagged.get(index) ?? [];
  const at = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setPct(Math.round(Math.min(100, Math.max(0, ((e.clientX - r.left) / (r.width || 1)) * 100))));
  };
  const stop = () => (dragging.current = false);

  return (
    <div className="flex flex-col gap-3">
      <div
        data-testid="wipe-stage"
        className="relative aspect-[960/541] w-full cursor-ew-resize touch-pan-y select-none overflow-hidden rounded-lg bg-surface-2 has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-focus"
        onPointerDown={(e) => {
          dragging.current = true;
          e.currentTarget.setPointerCapture?.(e.pointerId);
          at(e);
          input.current?.focus({ preventScroll: true }); // arrows keep working after a drag
        }}
        onMouseDown={(e) => e.preventDefault()} // the default action would move focus off the range input again
        onPointerMove={(e) => dragging.current && at(e)}
        onPointerUp={stop}
        onPointerCancel={stop}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- local demo photos, fixed size */}
        <img src={pairSrc(run8, index, "a")} alt={`Listing, ${name.toLowerCase()}`} draggable={false} className={img} onError={() => setMissing(true)} />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={pairSrc(run8, index, "b")}
          alt={`Your scan, ${name.toLowerCase()}`}
          draggable={false}
          className={`${img} bg-surface-2`}
          style={{ clipPath: `inset(0 0 0 ${pct}%)` }}
          onError={() => setMissing(true)}
        />
        <div aria-hidden className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-mint" style={{ left: `${pct}%` }}>
          <span className="absolute top-1/2 left-1/2 flex size-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-mint bg-surface text-ink shadow-sm">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m9 6-6 6 6 6M15 6l6 6-6 6" /></svg>
          </span>
        </div>
        <span className={`${tag} left-2`}>Listing</span>
        <span className={`${tag} right-2`}>Your scan</span>
        <input
          ref={input}
          type="range"
          min={0}
          max={100}
          value={pct}
          onChange={(e) => setPct(Number(e.target.value))}
          aria-label="Compare the listing with your scan"
          aria-valuetext={`${pct}% listing, ${100 - pct}% your scan`}
          className="sr-only"
        />
      </div>

      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" aria-live="polite">
        <span className="font-semibold">{name}</span>
        {cats.length ? (
          cats.map((c) => (
            <span key={c} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="size-2 rounded-full bg-coral" />
              {CATEGORY_WORDS[c]}
            </span>
          ))
        ) : (
          <span className="text-ink-2">No difference flagged in this view.</span>
        )}
      </p>

      <ul ref={strip} aria-label="All compared views" className="m-0 flex list-none gap-2 overflow-x-auto p-0 pb-1 md:grid md:grid-cols-6 md:overflow-visible">
        {Array.from({ length: count }, (_, i) => {
          const c = flagged.get(i) ?? [];
          const label = viewName(viewLabel(i));
          return (
            <li key={i} className="shrink-0">
              <button
                type="button"
                aria-pressed={i === index}
                aria-label={c.length ? `${label}: ${c.map((x) => CATEGORY_WORDS[x]).join("; ")}` : label}
                onClick={() => onIndex(i)}
                className="flex w-24 flex-col gap-1 rounded-md bg-surface p-1 text-left text-xs transition-colors hover:border-ink aria-pressed:border-ink aria-pressed:ring-1 aria-pressed:ring-ink md:w-full"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={pairSrc(run8, i, "b")} alt="" loading="lazy" draggable={false} className="aspect-[960/541] w-full rounded-sm bg-surface-2 object-cover" />
                <span className="px-0.5 font-semibold">{label}</span>
                <span className="flex min-h-4 items-center gap-1 px-0.5 text-ink-2">
                  {c.length > 0 && (
                    <>
                      <span aria-hidden className="size-2 rounded-full bg-coral" />
                      Different
                    </>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
