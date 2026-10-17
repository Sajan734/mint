import type { ListingDoc } from "./types";

export type Phase = "waiting" | "scanning" | "writing" | "listed" | "rejected" | "failed";

export const STEPS: { phase: Phase; label: string; hint: string }[] = [
  { phase: "waiting", label: "Scan it with your iPhone", hint: "Point the camera at the code. The Mint app opens and records 20 s." },
  { phase: "scanning", label: "Building the 3D scan", hint: "About 30 seconds after the upload" },
  { phase: "writing", label: "Writing your listing", hint: "Name, description, condition and a fair price" },
  { phase: "listed", label: "Ready to review", hint: "Check it, then publish" },
];

/** The splat job's stages in order (gsplat/mintsplat/pipeline.py), for a progress bar while it runs. */
const SPLAT_STAGES = ["1_frames", "2_masks", "3_poses", "4_train", "5_clean_export", "6_views"];

export interface Progress {
  stages: Record<string, string>; // stage -> latest status from Realtime ("started", "done", ...)
  manifest: boolean; // the 3D scan is published
  listing: ListingDoc | null; // the listing step finished (any status)
}

export function phaseOf(p: Progress): Phase {
  if (p.listing) return p.listing.status;
  if (p.manifest || p.stages["7_listing"]) return "writing";
  if (Object.keys(p.stages).length) return "scanning";
  return "waiting";
}

/** 0..1 through the splat stages; per-video stage names ("2_masks_top") count once. */
export function splatFraction(stages: Record<string, string>): number {
  const done = SPLAT_STAGES.filter((s) => Object.entries(stages).some(([k, v]) => k.startsWith(s) && v === "done"));
  return done.length / SPLAT_STAGES.length;
}

export function stepState(step: Phase, current: Phase): "done" | "active" | "todo" {
  const order: Phase[] = ["waiting", "scanning", "writing", "listed"];
  const at = order.indexOf(current === "rejected" || current === "failed" ? "writing" : current);
  const i = order.indexOf(step);
  if (current === "listed" || i < at) return "done";
  return i === at ? "active" : "todo";
}
