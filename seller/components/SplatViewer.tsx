// Twin: buyer/components/SplatViewer.tsx (keep identical)
// 3D Gaussian splat viewer (three + Spark behind lib/splat-scene, loaded in an effect, never on the server).
// - Fills its parent: size the parent (for example `aspect-square`). Opaque `surface-2` background.
// - Shows `poster` until the first splat frame is drawn, then fades the splat in. On error, or when another viewer
//   takes its WebGL slot (max 2 live, lib/viewer-slots), it shows the poster again.
// - Synced cameras (for a splat wipe): pass the SAME `sharedPose` ref object to two viewers. Dragging either one
//   moves both. Start it as `{ current: { azimuth: 0, polar: 0, distance: 0 } }`; distance 0 means "frame me".
// - `autoRotate` is ignored under prefers-reduced-motion and stops at the first drag or key press.
// - Keyboard (interactive): arrow keys turn, + and - zoom.
"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { CameraPose, SceneHandle } from "@/lib/splat-scene";
import { acquireSlot } from "@/lib/viewer-slots";

export type { CameraPose };
export interface SplatViewerProps {
  src: string; // .spz / .ply / .splat URL, CORS-enabled
  label: string; // accessible name, e.g. "3D view of the ThinkPad mouse"
  autoRotate?: boolean; // default true
  interactive?: boolean; // orbit + zoom, default false (cards)
  poster?: string; // still image shown until the first frame is drawn, and on error
  className?: string;
  maxPixelRatio?: number; // default 2
  sharedPose?: { current: CameraPose }; // same ref in two viewers = synced cameras
  onLoad?: () => void;
  onError?: (e: Error) => void;
}

const reducedMotion = () =>
  typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const toError = (e: unknown) => (e instanceof Error ? e : new Error(String(e)));

let preloaded = false;
/** Warm the three + Spark chunks on idle, so the first hover only waits for the splat file. */
export function preloadSplatScene(): void {
  if (preloaded || typeof window === "undefined") return;
  preloaded = true;
  const go = () => {
    import("@/lib/splat-scene")
      .then((m) => m.loadEngine())
      .catch(() => { preloaded = false; }); // only a warm-up: the real mount reports load errors
  };
  if ("requestIdleCallback" in window) window.requestIdleCallback(go, { timeout: 4000 });
  else setTimeout(go, 1500);
}

type Phase = "loading" | "ready" | "failed" | "paused";

// A new src is a new scene: the key resets every piece of state.
export default function SplatViewer(props: SplatViewerProps) {
  return <Scene key={props.src} {...props} />;
}
export { SplatViewer };

function Scene({
  src, label, poster, autoRotate = true, interactive = false, maxPixelRatio = 2, sharedPose, onLoad, onError, className,
}: SplatViewerProps) {
  const host = useRef<HTMLDivElement>(null);
  const id = useId();
  const [phase, setPhase] = useState<Phase>("loading");
  const [touched, setTouched] = useState(false);
  const cb = useRef({ onLoad, onError }); // latest callbacks without rebuilding the WebGL context
  useEffect(() => { cb.current = { onLoad, onError }; });
  const live = phase === "loading" || phase === "ready";

  useEffect(() => {
    const el = host.current;
    if (!el || !live) return;
    let cancelled = false;
    let handle: SceneHandle | undefined;
    const release = acquireSlot(id, () => { if (!cancelled) setPhase("paused"); });
    const fail = (e: unknown) => {
      if (cancelled) return;
      setPhase("failed");
      cb.current.onError?.(toError(e));
    };
    import("@/lib/splat-scene")
      .then(({ mountSplatScene }) =>
        mountSplatScene(el, {
          src, interactive, maxPixelRatio, sharedPose,
          autoRotate: autoRotate && !reducedMotion(),
          onReady: () => { if (!cancelled) { setPhase("ready"); cb.current.onLoad?.(); } },
          onError: fail,
        }),
      )
      .then((h) => { if (cancelled) h.dispose(); else handle = h; })
      .catch(fail);
    return () => {
      cancelled = true;
      release();
      handle?.dispose();
    };
  }, [id, live, src, autoRotate, interactive, maxPixelRatio, sharedPose]);

  const pill = "pointer-events-none absolute rounded-full border border-line-strong bg-surface px-3 py-1 text-sm leading-tight text-ink";
  return (
    <div
      ref={host}
      aria-label={label}
      {...(interactive
        ? {
            role: "application",
            "aria-roledescription": "3D viewer",
            "aria-describedby": `${id}-help`,
            tabIndex: 0,
            onPointerDown: () => setTouched(true),
            onKeyDown: () => setTouched(true),
          }
        : { role: "img" })}
      className={`relative h-full w-full overflow-hidden bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus ${className ?? ""}`}
    >
      {poster && (
        // eslint-disable-next-line @next/next/no-img-element -- remote scan photo
        <img
          src={poster}
          alt=""
          draggable={false}
          className="pointer-events-none absolute inset-0 h-full w-full object-contain transition-opacity duration-200"
          style={{ opacity: phase === "ready" ? 0 : 1 }}
        />
      )}
      {interactive && (
        <>
          <span id={`${id}-help`} className="sr-only">Drag or use the arrow keys to turn it. Plus and minus zoom.</span>
          {phase === "loading" && <span role="status" className={`${pill} bottom-2 left-2`}>Loading 3D…</span>}
          {phase === "ready" && !touched && (
            <span className={`${pill} bottom-2 left-1/2 -translate-x-1/2 whitespace-nowrap`}>Drag to turn</span>
          )}
          {phase === "paused" && (
            <button
              type="button"
              onClick={() => setPhase("loading")}
              className="absolute left-1/2 top-1/2 min-h-11 -translate-x-1/2 -translate-y-1/2 rounded-full border border-line-strong bg-surface px-4 text-sm font-semibold text-ink hover:bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            >
              Show 3D
            </button>
          )}
        </>
      )}
      {phase === "failed" && <span className={`${pill} bottom-2 left-2`}>3D view not available</span>}
    </div>
  );
}
