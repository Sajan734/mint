"""Pydantic v2 models for the buyer agent (DESIGN s4 + amendments AM-05/06/20/21)."""

from collections.abc import Iterable
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from buyer_agent.errors import AgentError, ErrorCode

Prob = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
Num = Annotated[float, Field(allow_inf_nan=False)]
Label = Annotated[str, Field(min_length=1, max_length=80)]
VerdictLabel = Literal[
    "same", "different", "uncertain", "alignment_failed", "scan_quality_poor", "listing_rejected"
]
Category = Literal["shape_diff", "part_diff", "color_diff", "any_diff"]
ActionCategory = Literal[
    "none", "request_more_photos", "message_seller", "request_refund", "escalate"
]


class Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def unique_labels(labels: Iterable[str]) -> None:
    seen: set[str] = set()
    for label in labels:
        if label in seen:
            raise AgentError(ErrorCode.INPUT_INVALID, f"duplicate view label: {label}")
        seen.add(label)


class SplatRef(Strict):
    path: Annotated[str, Field(max_length=512)]  # relative to DATA_ROOT; no URLs in v1
    format: Literal["ply", "splat"]
    up_axis: Literal["-y", "+y", "+z"] = "-y"
    scan_id: str | None = None


class ViewPairsRef(Strict):
    manifest_path: Annotated[str, Field(max_length=512)]  # pairs.json under DATA_ROOT


class Price(Strict):
    amount: Annotated[float, Field(ge=0, le=1e6, allow_inf_nan=False)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class ListingClaims(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    title: Annotated[str, Field(min_length=1, max_length=200)]
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    specs: Annotated[dict[str, str], Field(max_length=20)] = Field(default_factory=dict)
    condition_grade: Annotated[float, Field(ge=1, le=10, allow_inf_nan=False)] | None = None
    condition_notes: Annotated[
        list[Annotated[str, Field(max_length=200)]], Field(max_length=10)
    ] = Field(default_factory=list)
    accessories_included: Annotated[
        list[Annotated[str, Field(max_length=100)]], Field(max_length=10)
    ] = Field(default_factory=list)
    price: Price | None = None


class ListingMatchCheck(Strict):
    """Mirrors the teammate's `MatchCheck` (verdict + reason); `mismatch` = listing rejected."""

    verdict: Literal["match", "mismatch", "uncertain"]
    reason: Annotated[str, Field(max_length=300)]


class CompareRequest(Strict):
    comparison_id: UUID  # idempotency key, set by caller
    listing_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    listing_splat: SplatRef | None = None
    buyer_splat: SplatRef | None = None
    view_pairs: ViewPairsRef | None = None
    claims: ListingClaims | None = None
    listing_match_check: ListingMatchCheck | None = None
    attempt: Annotated[int, Field(ge=1, le=5)] = 1

    @model_validator(mode="after")
    def _one_mode(self) -> "CompareRequest":
        has_splats = self.listing_splat is not None and self.buyer_splat is not None
        half_splats = (self.listing_splat is None) != (self.buyer_splat is None)
        if half_splats or has_splats == (self.view_pairs is not None):
            raise ValueError(
                "give either listing_splat+buyer_splat or view_pairs, not both/neither"
            )
        return self


class ViewPair(Strict):
    label: Label
    azimuth_deg: Num | None = None
    elevation_deg: Num | None = None
    png_a: bytes = Field(exclude=True, repr=False)  # seller
    png_b: bytes = Field(exclude=True, repr=False)  # buyer


class JevViewScores(Strict):
    view: Label
    model: str
    viewpoint_match: Prob
    scan_quality_ok: Prob
    shape_diff: Prob
    part_diff: Prob
    color_diff: Prob
    any_diff: Prob
    latency_ms: int


class ViewFailure(Strict):
    view: Label
    code: str  # ErrorCode value; detail lives in the run log only (AM-20)


class CategoryEvidence(Strict):
    evidence: Prob  # support-th highest value
    max: Prob
    views: list[Label]  # views >= threshold.different


class AlignmentMetrics(Strict):
    rmse: Num
    a_covered: Prob
    b_covered: Prob
    ambiguity: Prob
    scale: Num


class Evidence(Strict):
    requested_views: int
    answered_views: int
    usable_views: int
    failed_views: list[ViewFailure]
    categories: dict[Category, CategoryEvidence]
    flagged: list[Category]
    alignment: AlignmentMetrics | None
    alignment_mode: Literal["icp", "skipped_view_pairs"]

    @model_validator(mode="after")
    def _unique_failed(self) -> "Evidence":
        unique_labels(f.view for f in self.failed_views)
        return self


class Verdict(Strict):
    label: VerdictLabel
    evidence_score: Prob | None  # ordinal, not a probability; only for same/different
    reason: str
    evidence: Evidence
    caveats: list[str]


class ClaimsFinding(Strict):
    claim: str
    source: Literal["accessory", "condition_note", "condition_grade"]
    status: Literal["supported", "contradicted", "unverifiable"]
    p_present: Prob | None
    views: list[Label]


class NextStep(Strict):
    category: ActionCategory
    audience: Literal["none", "buyer", "seller", "support"]
    reason_code: str  # planner row id, e.g. "R4"
    summary: Annotated[str, Field(max_length=400)]
    message_to_seller: Annotated[str, Field(max_length=1200)] | None
    refund_request: Annotated[str, Field(max_length=1200)] | None
    cited_views: list[Label]
    drafted_by: str  # "groq:openai/gpt-oss-120b" | "template"
    is_template: bool


class Explanation(Strict):
    headline: str
    what_we_compared: str
    what_we_found: list[str]
    how_sure: str
    listing_vs_item: list[str]
    what_to_do: list[str]
    caveats: list[str]
    disclaimer: str
    friendly_summary: str | None = None


class ErrorInfo(Strict):
    code: str
    message: str  # plain language


class CompareResponse(Strict):
    v: Literal[1] = 1
    comparison_id: UUID
    status: Literal["done", "failed"]
    verdict: Verdict | None
    claims_available: bool
    claims_findings: list[ClaimsFinding]
    next_step: NextStep | None
    explanation: Explanation | None = None
    error: ErrorInfo | None
    model_ids: dict[str, str]
    timings_ms: dict[str, int]
    run_id: str  # == comparison_id; folder name only
