// "How it matches": plain words for a CompareResponse and the recorded demo runs.
// Never turn evidence_score, evidence values or p_present into text: they are ordinal model scores (PLAN_UX section 4).
import type { ClaimsFinding, CompareResponse, EvidenceCategory, VerdictCause, VerdictLabel } from "./compare-types";
import r435 from "../mock/compare/435e1251.json";
import rcce from "../mock/compare/cce6fb01.json";

const HEADINGS: Record<VerdictLabel, string> = {
  same: "Looks like the same item",
  different: "Does not match the listing",
};
export const FAILED_HEADING = "Could not run the check, try again";

/** Why a "different" could not be confirmed. Shown under the heading. */
export const CAUSE_WORDS: Record<VerdictCause, string> = {
  low_quality: "Your scan was not clear enough to confirm a match",
  misaligned: "The two scans did not line up",
  listing_rejected: "The listing scan could not be used",
};
export const causeLine = (r: CompareResponse): string | null =>
  r.status === "done" && r.verdict?.cause ? CAUSE_WORDS[r.verdict.cause] : null;

export const heading = (r: CompareResponse): string =>
  r.status === "failed" || !r.verdict ? FAILED_HEADING : HEADINGS[r.verdict.label];

export const CATEGORY_WORDS: Record<EvidenceCategory, string> = {
  part_diff: "A part looks different or missing",
  color_diff: "Colours look different",
  shape_diff: "The shape looks different",
  any_diff: "Something looks different",
};

export const CLAIM_WORDS: Record<ClaimsFinding["status"], string> = {
  supported: "Seen in your scan",
  contradicted: "Not seen in your scan",
  unverifiable: "Cannot check from a scan",
};

const SUPABASE_URL = (process.env.NEXT_PUBLIC_SUPABASE_URL || "https://jpanyhsifoxxiizkgjno.supabase.co").replace(/\/$/, "");
export const run8 = (id: string) => id.slice(0, 8);

// Recorded demo runs: exact copies of multiagent/runs/{run}/response.json.
export type MockRun = "435e1251" | "cce6fb01";
const RUNS: Record<MockRun, CompareResponse> = {
  "435e1251": r435 as unknown as CompareResponse,
  cce6fb01: rcce as unknown as CompareResponse,
};
export const mockRun = (run: MockRun): CompareResponse => RUNS[run];
export const OTHER_ITEM_NOTE = "This recorded check is from a different item (a plant shelf).";

/** Which recorded run a listing replays. Pots and zen (or a listing built from their photos) get their own run. */
export function pickRun(listingId: string, frames: readonly string[] = []): { run: MockRun; note: string | null } {
  const first = frames[0] ?? "";
  if (listingId.startsWith("zen") || first.startsWith("/local/zen/")) return { run: "cce6fb01", note: null };
  if (listingId.startsWith("pots") || first.startsWith("/local/pots/")) return { run: "435e1251", note: null };
  return { run: "435e1251", note: OTHER_ITEM_NOTE };
}

export function runFooter(r: CompareResponse): string {
  const total = r.timings_ms.total;
  return `Run ${run8(r.run_id)}` + (typeof total === "number" ? ` · ${(total / 1000).toFixed(1)} s` : "");
}

/** The buyer's own 3D scan, if the pipeline published one (assets/splats/{cid}.json). Null when absent or offline. */
export async function fetchBuyerSplat(cid: string): Promise<string | null> {
  try {
    const res = await fetch(`${SUPABASE_URL}/storage/v1/object/public/assets/splats/${cid}.json?t=${Date.now()}`, { cache: "no-store" });
    const j = res.ok ? ((await res.json()) as { splat_url?: unknown }) : null;
    return typeof j?.splat_url === "string" ? j.splat_url : null;
  } catch {
    return null;
  }
}
