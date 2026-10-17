"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { PX_PER_FRAME, decay, loadOrder, wrapIndex } from "./spin-math";

type Props = {
  frames: string[];
  alt: string;
  variant: "card" | "detail";
  viewerUrl?: string | null;
  /**
   * SPLAT SLOT: when `viewerUrl` is set and `splat` is provided, it replaces the frame
   * viewer in the same 1:1 box. Later pass a lazily loaded Spark/three.js viewer here
   * (`dynamic(() => import(...), { ssr: false })`). Nothing three.js is installed now.
   */
  splat?: ReactNode;
};

const INTRO_MS = 6000;
const reducedMotion = () =>
  typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export default function SpinViewer({ frames, alt, variant, viewerUrl, splat }: Props) {
  const n = frames.length;
  const [index, setIndex] = useState(0);
  const [loaded, setLoaded] = useState<ReadonlySet<number>>(() => new Set([0]));
  const [failed, setFailed] = useState<ReadonlySet<number>>(() => new Set());
  const [touched, setTouched] = useState(false);
  const [preloading, setPreloading] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const pos = useRef(0); // float frame position
  const raf = useRef(0);
  const interacted = useRef(false);
  const preloadStarted = useRef(false);
  const drag = useRef<{ x: number; start: number; moves: { t: number; p: number }[] } | null>(null);

  const show = useCallback(
    (p: number) => {
      pos.current = p;
      setIndex(wrapIndex(Math.round(p), n));
    },
    [n],
  );

  const preload = useCallback(() => {
    if (preloadStarted.current || n < 2) return;
    preloadStarted.current = true;
    setPreloading(true);
    for (const i of loadOrder(Math.round(pos.current), n)) {
      if (i === 0) continue;
      const img = new Image();
      img.onload = () => setLoaded((s) => new Set(s).add(i));
      img.onerror = () => setFailed((s) => new Set(s).add(i));
      img.src = frames[i];
    }
  }, [frames, n]);

  // Lazy preload when the viewer enters the viewport.
  useEffect(() => {
    const el = root.current;
    if (!el || n < 2) return;
    if (typeof IntersectionObserver === "undefined") {
      preload();
      return;
    }
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) {
        preload();
        io.disconnect();
      }
    });
    io.observe(el);
    return () => io.disconnect();
  }, [n, preload]);

  // One-revolution intro turn; skipped under reduced motion or after any interaction.
  useEffect(() => {
    if (n < 2 || reducedMotion()) return;
    const t0 = performance.now();
    const tick = (t: number) => {
      if (interacted.current) return;
      const k = Math.min((t - t0) / INTRO_MS, 1);
      show(k < 1 ? k * n : 0);
      if (k < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [n, show]);

  if (viewerUrl && splat) return <div style={box}>{splat}</div>;
  if (n === 0) return <div role="img" aria-label={alt} style={box} />;

  const interact = () => {
    interacted.current = true;
    setTouched(true);
    cancelAnimationFrame(raf.current);
    preload();
  };
  const onDown = (e: React.PointerEvent) => {
    interact();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, start: pos.current, moves: [{ t: e.timeStamp, p: pos.current }] };
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const p = d.start - (e.clientX - d.x) / PX_PER_FRAME;
    d.moves.push({ t: e.timeStamp, p });
    show(p);
  };
  const onUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d || reducedMotion()) return;
    const recent = d.moves.filter((m) => e.timeStamp - m.t <= 80);
    const a = recent[0];
    const b = recent[recent.length - 1];
    let v = a && b && b.t > a.t ? ((b.p - a.p) / (b.t - a.t)) * 16 : 0; // frames per animation frame
    const step = () => {
      v = decay(v);
      if (v === 0) return;
      show(pos.current + v);
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
  };
  const onKey = (e: React.KeyboardEvent) => {
    const big = Math.max(1, Math.round(n / 8));
    const delta: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, PageUp: big, PageDown: -big };
    if (e.key === "Home") show(0);
    else if (e.key in delta) show(Math.round(pos.current) + delta[e.key]);
    else return;
    e.preventDefault();
    interact();
  };

  // Show the nearest usable frame; frame 0 is the safe fallback.
  const usable = (i: number) => loaded.has(i) && !failed.has(i);
  let shown = 0;
  for (let d = 0; d < n; d++) {
    const c = [wrapIndex(index - d, n), wrapIndex(index + d, n)].find(usable);
    if (c !== undefined) {
      shown = c;
      break;
    }
  }
  const interactive = n > 1;
  const pending = n - loaded.size - failed.size;

  return (
    <div
      ref={root}
      role={interactive ? "slider" : "img"}
      aria-label={`360 degree view of ${alt}`}
      {...(interactive && {
        tabIndex: 0,
        "aria-valuemin": 0,
        "aria-valuemax": n - 1,
        "aria-valuenow": index,
        "aria-valuetext": `Angle ${Math.round((index / n) * 360)} degrees`,
        onPointerDown: onDown,
        onPointerMove: onMove,
        onPointerUp: onUp,
        onPointerCancel: onUp,
        onKeyDown: onKey,
        onFocus: preload,
      })}
      style={{ ...box, touchAction: "pan-y", cursor: interactive ? "grab" : undefined, userSelect: "none" }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={frames[shown]}
        alt={alt}
        draggable={false}
        fetchPriority={shown === 0 ? "high" : undefined}
        onError={() => setFailed((s) => new Set(s).add(shown))}
        style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
      />
      {interactive && (
        <>
          <span style={tag}>360</span>
          {variant === "detail" && !touched && <span style={hint}>Drag to spin</span>}
          {preloading && pending > 0 && (
            <span
              aria-hidden
              style={{
                position: "absolute",
                left: 0,
                bottom: 0,
                height: 3,
                background: "var(--mint)",
                width: `${(loaded.size / n) * 100}%`,
                transition: "width var(--dur-state) var(--ease)",
              }}
            />
          )}
        </>
      )}
    </div>
  );
}

const box: CSSProperties = {
  position: "relative",
  aspectRatio: "1 / 1",
  width: "100%",
  overflow: "hidden",
  backgroundColor: "var(--surface)",
  borderRadius: "var(--r-md)",
};
// Paper pills (raised + ink) keep contrast on the shelf in both themes (docs/design/DESIGN.md §4).
const pill: CSSProperties = {
  position: "absolute",
  fontSize: "var(--t-sm)",
  fontFamily: "var(--font-sans)",
  fontWeight: 500,
  lineHeight: 1,
  color: "var(--ink)",
  background: "var(--raised)",
  padding: "7px var(--sp-3)",
  borderRadius: 999,
  pointerEvents: "none",
};
const tag: CSSProperties = { ...pill, right: "var(--sp-2)", bottom: "var(--sp-2)" };
const hint: CSSProperties = {
  ...pill,
  left: "50%",
  bottom: "var(--sp-2)",
  transform: "translateX(-50%)",
  whiteSpace: "nowrap",
  fontFamily: "var(--font-figtree), system-ui, sans-serif",
  fontSize: "var(--t-sm)",
  padding: "6px var(--sp-3)",
};
