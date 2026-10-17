// Twin: buyer/components/MediaPanel.tsx (identical except the frame spinner import, marked FRAME SPINNER)
// Item media: one big square view (3D or the selected photo) and a row of tiles ("3D", then up to 3 photos).
// Use <MediaPanel .../> for the stacked default, or <MediaProvider> + <MediaViewer/> + <MediaTiles/> to place the
// two parts yourself (the selection lives in the provider).
"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import SplatViewer from "./SplatViewer";
// FRAME SPINNER (seller): the existing frame viewer, the 3D view when there is no splat.
import Spin from "./Spin";
const FrameSpin = ({ frames, alt }: { frames: string[]; alt: string }) => <Spin frames={frames} alt={alt} />;

export type MediaSelection = "3d" | number; // "3d" or an index into photos

export interface MediaPanelProps {
  title: string;
  splatUrl: string | null;
  frames: string[]; // spin frames, the 3D fallback when there is no splat
  photos: string[]; // real photos of the item (max 3 shown)
  sample?: boolean; // splatUrl is a sample, not this item: labelled "Sample 3D, not this item"
}

const MAX_PHOTOS = 3;
// Held-out photos are masked onto black, so every photo sits on the brand's near-black (stage) surface.
const PHOTO_BG = "bg-[#0b0f0e]";

type Ctx = MediaPanelProps & {
  has3d: boolean;
  selected: MediaSelection;
  select: (s: MediaSelection) => void;
  broken: ReadonlySet<string>;
  markBroken: (src: string) => void;
};
const MediaCtx = createContext<Ctx | null>(null);

function useMedia(): Ctx {
  const c = useContext(MediaCtx);
  if (!c) throw new Error("MediaViewer and MediaTiles must sit inside <MediaProvider>");
  return c;
}

export function MediaProvider({ children, ...p }: MediaPanelProps & { children: ReactNode }) {
  const [picked, select] = useState<MediaSelection>("3d");
  const [broken, setBroken] = useState<ReadonlySet<string>>(() => new Set());
  const has3d = !!p.splatUrl || p.frames.length > 0;
  const nPhotos = Math.min(p.photos.length, MAX_PHOTOS);
  // Props can change under us (data arrives late): fall back to whatever exists.
  const selected: MediaSelection =
    picked === "3d" ? (has3d || nPhotos === 0 ? "3d" : 0) : picked < nPhotos ? picked : has3d || nPhotos === 0 ? "3d" : 0;
  const markBroken = (src: string) => setBroken((s) => (s.has(src) ? s : new Set(s).add(src)));
  return (
    <MediaCtx.Provider value={{ ...p, has3d, selected, select, broken, markBroken }}>{children}</MediaCtx.Provider>
  );
}

const BOX = "relative aspect-square w-full overflow-hidden rounded-md";
const PILL = "pointer-events-none absolute rounded-full bg-raised px-3 py-1.5 text-sm font-semibold leading-tight text-ink";

export function MediaViewer({ className = "" }: { className?: string }) {
  const { title, splatUrl, frames, photos, sample, selected, broken, markBroken } = useMedia();
  const [failedUrl, setFailedUrl] = useState<string | null>(null);

  if (typeof selected === "number") {
    const src = photos[selected];
    return (
      <div className={`${BOX} ${PHOTO_BG} ${className}`}>
        {broken.has(src) ? (
          <span className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-[#b0bab6]">
            Photo not on this machine
          </span>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element -- scan photos come from storage or /public
          <img
            src={src}
            alt={`${title}, photo ${selected + 1}`}
            onError={() => markBroken(src)}
            className="h-full w-full object-contain"
          />
        )}
      </div>
    );
  }
  // A failed splat falls back to the frame spinner when there are frames; otherwise SplatViewer shows its note.
  if (splatUrl && (failedUrl !== splatUrl || frames.length === 0)) {
    return (
      <div className={`${BOX} ${className}`}>
        <SplatViewer
          src={splatUrl}
          label={sample ? `Sample 3D view, not ${title}` : `3D view of ${title}`}
          interactive
          autoRotate
          poster={sample ? undefined : (frames[0] ?? photos[0])}
          onError={() => setFailedUrl(splatUrl)}
        />
        {sample && <span className={`${PILL} left-2 top-2`}>Sample 3D, not this item</span>}
      </div>
    );
  }
  if (frames.length > 0) {
    return (
      <div className={className}>
        <FrameSpin frames={frames} alt={title} />
      </div>
    );
  }
  return (
    <div className={`${BOX} bg-surface-2 ${className}`} role="img" aria-label={title}>
      <span className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-ink-2">No photos yet</span>
    </div>
  );
}

function CubeIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
      <path d="M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Z" />
      <path d="M4 7.5 12 12l8-4.5M12 12v9" />
    </svg>
  );
}

export function MediaTiles({ className = "" }: { className?: string }) {
  const { title, photos, has3d, selected, select, broken, markBroken } = useMedia();
  const shown = photos.slice(0, MAX_PHOTOS);
  if ((has3d ? 1 : 0) + shown.length < 2) return null; // one view needs no picker
  const tile = (on: boolean) =>
    `relative grid size-16 shrink-0 place-items-center overflow-hidden rounded-[12px] bg-surface transition-[background-color,box-shadow] duration-150 md:size-20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${
      on ? "ring-2 ring-leaf ring-offset-2 ring-offset-bg" : "hover:bg-surface-2"
    }`;
  return (
    <div role="group" aria-label={`Views of ${title}`} className={`flex flex-wrap gap-2 ${className}`}>
      {has3d && (
        <button
          type="button"
          aria-pressed={selected === "3d"}
          aria-label="3D view"
          onClick={() => select("3d")}
          className={`${tile(selected === "3d")} bg-surface-2 text-ink`}
        >
          <span className="flex flex-col items-center gap-0.5">
            <CubeIcon />
            <span className="text-xs font-semibold leading-none">3D</span>
          </span>
        </button>
      )}
      {shown.map((src, i) => (
        <button
          key={`${i}:${src}`}
          type="button"
          aria-pressed={selected === i}
          aria-label={`View ${i + 1}`}
          onClick={() => select(i)}
          className={`${tile(selected === i)} ${PHOTO_BG}`}
        >
          {broken.has(src) ? (
            <span className="p-1 text-center text-xs leading-tight text-[#b0bab6]">Missing</span>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- scan photos come from storage or /public
            <img src={src} alt="" loading="lazy" onError={() => markBroken(src)} className="h-full w-full object-contain" />
          )}
        </button>
      ))}
    </div>
  );
}

export default function MediaPanel({ className = "", ...p }: MediaPanelProps & { className?: string }) {
  return (
    <MediaProvider {...p}>
      <div className={`flex flex-col gap-3 ${className}`}>
        <MediaViewer />
        <MediaTiles />
      </div>
    </MediaProvider>
  );
}
export { MediaPanel };
