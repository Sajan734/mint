"use client";

import { useEffect, useRef, useState } from "react";

const AUTO_MS = 140; // turntable speed until someone grabs it
const PX_PER_FRAME = 12;

/** Drag (or use the slider) to turn the scanned item. Frames are ordered by azimuth (24 = every 15 deg). */
export default function Spin({ frames, alt }: { frames: string[]; alt: string }) {
  const n = frames.length;
  const [i, setI] = useState(0);
  const [auto, setAuto] = useState(true);
  const drag = useRef<{ x: number; start: number } | null>(null);

  useEffect(() => {
    frames.forEach((src) => { new Image().src = src; }); // preload so turning never flickers
  }, [frames]);

  useEffect(() => {
    if (!auto || n < 2) return;
    const t = setInterval(() => setI((v) => (v + 1) % n), AUTO_MS);
    return () => clearInterval(t);
  }, [auto, n]);

  if (!n) return null;
  return (
    <div className="flex w-full flex-col items-center gap-3">
      {/* eslint-disable-next-line @next/next/no-img-element -- remote frames from Supabase Storage */}
      <img
        src={frames[i]}
        alt={alt}
        draggable={false}
        className="aspect-square w-full max-w-[480px] cursor-grab touch-none select-none object-contain active:cursor-grabbing"
        onPointerDown={(e) => {
          setAuto(false);
          drag.current = { x: e.clientX, start: i };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!drag.current) return;
          const step = Math.round((drag.current.x - e.clientX) / PX_PER_FRAME);
          setI((((drag.current.start + step) % n) + n) % n);
        }}
        onPointerUp={() => { drag.current = null; }}
      />
      <input
        type="range"
        min={0}
        max={n - 1}
        value={i}
        onChange={(e) => { setAuto(false); setI(Number(e.target.value)); }}
        aria-label="Turn the item"
        className="w-48 accent-[var(--mint)]"
      />
    </div>
  );
}
