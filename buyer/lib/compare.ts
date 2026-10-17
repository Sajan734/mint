// "How it matches": plain words for a CompareResponse, the view-image mapping, and the recorded demo runs.
// Never turn evidence_score, evidence values or p_present into text: they are ordinal model scores (PLAN_UX section 4).
import type { ClaimsFinding, CompareResponse, EvidenceCategory, VerdictLabel } from "./compare-types";
import r435 from "../mock/compare/435e1251.json";
import rcce from "../mock/compare/cce6fb01.json";

const HEADINGS: Record<VerdictLabel, string> = {
  same: "Looks like the same item",
  different: "Does not match the listing",
  uncertain: "We cannot tell",
  alignment_failed: "The two scans do not line up",
  scan_quality_poor: "Your scan is not clear enough",
  listing_rejected: "The listing scan cannot be used",
};
export const FAILED_HEADING = "The check did not finish";

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

// The buyer agent saves pair i (0-based) as a_{ii}.png / b_{ii}.png and labels it "view_{i+1}"
// (multiagent/buyer_agent/pipeline.py _save_pairs; runs/fc4b95cb.../jev/view_00.json holds "view_01").
const pad = (n: number) => String(n).padStart(2, "0");
export const viewLabel = (index: number) => `view_${pad(index + 1)}`;
export function viewIndex(label: string): number | null {
  const m = /^view_(\d+)$/.exec(label);
  const n = m ? Number(m[1]) : 0;
  return n >= 1 ? n - 1 : null;
}
export const viewName = (label: string) => `View ${(viewIndex(label) ?? -1) + 1}`;
const SUPABASE_URL = (process.env.NEXT_PUBLIC_SUPABASE_URL || "https://jpanyhsifoxxiizkgjno.supabase.co").replace(/\/$/, "");
/** The recorded demo runs' pairs are 960 px WebP in the gitignored public/local/compare/{run8}/ (T7). A live check's
 *  pairs are the buyer agent's PNG thumbnails, published by gsplat/app.py run_verify to assets/comparisons/{run8}/. */
export const pairSrc = (run8: string, index: number, side: "a" | "b") =>
  run8 in RUNS
    ? `/local/compare/${run8}/${side}_${pad(index)}.webp`
    : `${SUPABASE_URL}/storage/v1/object/public/assets/comparisons/${run8}/${side}_${pad(index)}.png`;
export const run8 = (id: string) => id.slice(0, 8);

/** View index -> the flagged categories seen in that view, in `flagged` order. */
export function flaggedByView(r: CompareResponse): Map<number, EvidenceCategory[]> {
  const out = new Map<number, EvidenceCategory[]>();
  const ev = r.verdict?.evidence;
  for (const c of ev?.flagged ?? []) {
    for (const v of ev?.categories[c]?.views ?? []) {
      const i = viewIndex(v);
      if (i !== null) out.set(i, [...(out.get(i) ?? []), c]);
    }
  }
  return out;
}

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
