// Twin: buyer/lib/compare-types.ts (keep identical)
// TypeScript mirror of multiagent/buyer_agent/models.py: CompareResponse and the models inside it
// (Evidence, Verdict, ClaimsFinding, NextStep, Explanation, ErrorInfo). UUIDs are plain strings here.
// Prob fields are 0..1 floats. Never show evidence_score or p_present as a number to people (PLAN_UX section 4).

export type VerdictLabel =
  | "same"
  | "different"
  | "uncertain"
  | "alignment_failed"
  | "scan_quality_poor"
  | "listing_rejected";
/** models.py `Category`: what kind of difference a view showed. */
export type EvidenceCategory = "shape_diff" | "part_diff" | "color_diff" | "any_diff";
export type ActionCategory = "none" | "request_more_photos" | "message_seller" | "request_refund" | "escalate";

export interface ViewFailure {
  view: string; // "view_01" ... (1-based; image file a_NN / b_NN is NN = number - 1)
  code: string;
}

export interface CategoryEvidence {
  evidence: number;
  max: number;
  views: string[]; // views at or above the "different" threshold
}

export interface AlignmentMetrics {
  rmse: number;
  a_covered: number;
  b_covered: number;
  ambiguity: number;
  scale: number;
}

export interface Evidence {
  requested_views: number;
  answered_views: number;
  usable_views: number;
  failed_views: ViewFailure[];
  categories: Partial<Record<EvidenceCategory, CategoryEvidence>>; // a dict in Python: any key may be absent
  flagged: EvidenceCategory[];
  alignment: AlignmentMetrics | null;
  alignment_mode: "icp" | "skipped_view_pairs";
}

export interface Verdict {
  label: VerdictLabel;
  evidence_score: number | null; // ordinal, not a probability; only for same/different
  reason: string;
  evidence: Evidence;
  caveats: string[];
}

export interface ClaimsFinding {
  claim: string;
  source: "accessory" | "condition_note" | "condition_grade";
  status: "supported" | "contradicted" | "unverifiable";
  p_present: number | null;
  views: string[];
}

export interface NextStep {
  category: ActionCategory;
  audience: "none" | "buyer" | "seller" | "support";
  reason_code: string; // planner row id, e.g. "R4"
  summary: string;
  message_to_seller: string | null;
  refund_request: string | null;
  cited_views: string[];
  drafted_by: string; // "groq:openai/gpt-oss-120b" | "template"
  is_template: boolean;
}

export interface Explanation {
  headline: string;
  what_we_compared: string;
  what_we_found: string[];
  how_sure: string;
  listing_vs_item: string[];
  what_to_do: string[];
  caveats: string[];
  disclaimer: string;
  friendly_summary?: string | null;
}

export interface ErrorInfo {
  code: string;
  message: string; // plain language
}

export interface CompareResponse {
  v: 1;
  comparison_id: string;
  status: "done" | "failed";
  verdict: Verdict | null;
  claims_available: boolean;
  claims_findings: ClaimsFinding[];
  next_step: NextStep | null;
  explanation?: Explanation | null; // absent in 4 of 7 recorded runs
  error: ErrorInfo | null;
  model_ids: Record<string, string>;
  timings_ms: Record<string, number>;
  run_id: string; // == comparison_id; folder name only
}
