// Twin: seller/lib/progress.ts (keep identical)
// The phone scan's visible steps, and the words for each pipeline stage. Stage names come from
// gsplat/mintsplat/pipeline.py and gsplat/app.py ("7_listing"); a check's sub-steps are the buyer agent's
// timings_ms keys (multiagent/buyer_agent: judge, claims, advise).
import type { Phase } from "./scan-feed";

export type ScanKind = "listing" | "verify";
export type StepId = "waiting" | "connected" | "uploading" | "processing" | "ready";
/** Every mark has its own icon and word in the UI, never colour only. */
export type StepMark = "done" | "active" | "todo" | "stopped";

export interface Step {
  id: StepId;
  label: string;
  hint: string;
}

const PHONE_STEPS: Step[] = [
  { id: "waiting", label: "Scan this code with your iPhone", hint: "The Mint app opens and records the item." },
  { id: "connected", label: "Phone connected", hint: "Turn the item slowly while the app records." },
  { id: "uploading", label: "Uploading your scan", hint: "Keep the Mint app open." },
];

export const STEPS: Record<ScanKind, Step[]> = {
  listing: [
    ...PHONE_STEPS,
    { id: "processing", label: "Building your listing", hint: "3D scan, description and a fair price." },
    { id: "ready", label: "Your listing is ready", hint: "Check it, then publish." },
  ],
  verify: [
    ...PHONE_STEPS,
    { id: "processing", label: "Comparing with the listing", hint: "Mint checks your scan against the seller's." },
    { id: "ready", label: "Result ready", hint: "See how it matches." },
  ],
};

const ORDER: StepId[] = ["waiting", "connected", "uploading", "processing", "ready"];

/** Where each step stands in a phase. A rejected or failed scan stops at processing; a cancel on the phone stops
 *  at "Phone connected" (the phone can only cancel while its scanner is open). */
export function stepMark(step: StepId, phase: Phase): StepMark {
  if (phase === "ready") return "done";
  const stop = phase === "rejected" || phase === "failed" ? "processing" : phase === "cancelled" ? "connected" : null;
  const at = ORDER.indexOf(stop ?? (phase as StepId));
  const i = ORDER.indexOf(step);
  if (i < at) return "done";
  if (i > at) return "todo";
  return stop ? "stopped" : "active";
}

// Prefix -> words. Per-video names ("2_masks_top", "3_poses_bottom") match their prefix.
const SUB_STEPS: [string, string][] = [
  ["1_frames", "Reading the video"],
  ["2_masks", "Finding the item"],
  ["3_poses", "Working out the angles"],
  ["3b_register", "Working out the angles"],
  ["4_train", "Building the 3D model"],
  ["5_clean_export", "Cleaning up"],
  ["6_views", "Cleaning up"],
  ["judge", "Comparing views"],
  ["claims", "Checking the listing's claims"],
  ["advise", "Writing advice"],
];

/** The words for a pipeline stage, or null for a stage we do not know (the UI keeps the last words). */
export function subStepLabel(stage: string, kind: ScanKind): string | null {
  if (stage.startsWith("7_listing")) return kind === "verify" ? "Comparing with the listing" : "Writing your listing";
  return SUB_STEPS.find(([prefix]) => stage.startsWith(prefix))?.[1] ?? null;
}

/** The stages a demo listing replays, one per distinct sub-step (6_views shares "Cleaning up"). */
export const MOCK_LISTING_STAGES = ["1_frames", "2_masks", "3_poses", "4_train", "5_clean_export", "7_listing"];
/** A demo check replays these, each for as long as the recorded run's timings_ms says. */
export const MOCK_CHECK_STAGES = ["judge", "claims", "advise"];
