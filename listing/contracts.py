"""Contracts for the listing pipeline. Source of truth for every stage's inputs and outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Prob = Annotated[float, Field(ge=0.0, le=1.0)]

Grade = Literal["like_new", "light_wear", "moderate_wear", "heavy_wear"]
Verdict = Literal["match", "mismatch", "uncertain"]
UpAxis = Literal["+x", "-x", "+y", "-y", "+z", "-z"]
PriceBasis = Literal["new_retail", "used_comps", "llm_estimate"]
DefectKind = Literal[
    "scratch", "scuff", "dent", "crack", "stain", "discoloration", "wear", "missing_part", "other"
]
DealLabel = Literal["great", "good", "fair", "high", "overpriced"]
Confidence = Literal["high", "medium", "low"]
HighlightStatus = Literal["pending", "produced", "skipped", "failed"]


def _normalise(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def backed_by_text(value: str, visible_text: list[str]) -> bool:
    """True if `value` appears in some visible text, ignoring case, spaces and punctuation."""
    needle = _normalise(value)
    return bool(needle) and any(needle in _normalise(text) for text in visible_text)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunContext(Contract):
    """Per-run settings passed explicitly to every stage (no global state)."""

    item_id: str
    item_dir: Path
    run_dir: Path
    cache_dir: Path
    demo_mode: bool = False
    demo_offline: bool = False  # demo mode that never calls an API: a cache miss in an API stage is an error
    manual_baseline: bool = False  # use fixtures/<item>/baseline.* and never search
    up_axis: UpAxis = "+y"  # splat world axis pointing up; per item via input.json or --up-axis


class View(Contract):
    view_id: str
    label: str
    azimuth_deg: float
    elevation_deg: float
    image_path: str  # relative to listing/


class Views(Contract):
    item_id: str
    views: list[View] = Field(min_length=1)


class Identity(Contract):
    category: str
    brand: str | None = None
    model: str | None = None
    visible_text: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    search_query: str
    confidence: Prob

    @model_validator(mode="after")
    def _brand_and_model_backed_by_visible_text(self) -> Identity:
        for name in ("brand", "model"):
            value = getattr(self, name)
            if value is not None and not backed_by_text(value, self.visible_text):
                raise ValueError(f"{name} {value!r} is not backed by visible_text")
        return self


class Baseline(Contract):
    query: str
    image_path: str | None  # None: nothing usable was found
    source_url: str | None = None
    source: Literal["image_search", "manual"]
    note: str | None = None


class MatchCheck(Contract):
    same_category: Prob | None  # None when there was no baseline to compare against
    same_product: Prob | None
    verdict: Verdict
    reason: str  # shown to the seller


class Rejection(Contract):
    item_id: str
    match_check: MatchCheck


class ReferencePrice(Contract):
    amount_cad: float = Field(gt=0)
    basis: PriceBasis
    note: str


class Defect(Contract):
    kind: DefectKind
    score: Prob
    view_ids: list[str] = Field(default_factory=list)


class Condition(Contract):
    grade: Grade
    grade_score: Prob
    grade_confidence: Prob
    defects: list[Defect] = Field(default_factory=list)
    usable_view_count: int = Field(ge=0)
    needs_seller_check: bool


class ViewBox(Contract):
    """A box in one view, in Gemini's native box format."""

    box_2d: Annotated[list[Annotated[int, Field(ge=0, le=1000)]], Field(min_length=4, max_length=4)]
    # [ymin, xmin, ymax, xmax], each 0..1000 of the view's height or width

    @model_validator(mode="after")
    def _ordered(self) -> ViewBox:
        ymin, xmin, ymax, xmax = self.box_2d
        if ymin >= ymax or xmin >= xmax:
            raise ValueError(f"box_2d {self.box_2d} is empty: needs ymin < ymax and xmin < xmax")
        return self


class DefectBox(ViewBox):
    """One visible mark of a defect in one view."""

    kind: DefectKind


class DesignBox(ViewBox):
    """Printed text, a logo or a brand mark that is part of the product's design, in one view."""

    label: str  # what it reads or shows, e.g. "ThinkPad"


class HighlightMark(Contract):
    kind: DefectKind
    view_ids: list[str]  # the views it was located in
    gaussian_count: int = Field(ge=1)


class Highlight(Contract):
    """A copy of the seller's splat with the noted defects tinted red, or why there is none (yet)."""

    status: HighlightStatus  # pending: still running; result.json is rewritten when it finishes
    splat_path: str | None = None  # relative to listing/; set exactly when produced
    summary: str  # what was marked, or why no highlighted splat was produced
    marks: list[HighlightMark] = Field(default_factory=list)
    gaussian_share: float | None = Field(default=None, ge=0.0, le=1.0)  # of the item's Gaussians tinted red
    debug_sheet: str | None = None  # relative to listing/: each searched view with its boxes | the highlighted render

    @model_validator(mode="after")
    def _path_iff_produced(self) -> Highlight:
        if (self.status == "produced") != (self.splat_path is not None):
            raise ValueError("splat_path must be set exactly when a highlighted splat was produced")
        return self


class DealRating(Contract):
    rating: DealLabel
    explanation: str
    asking_price_cad: float = Field(gt=0)
    asking_price_source: Literal["seller", "suggested"]  # suggested: no asking price was given, Mint's price is rated
    fair_price_cad: int = Field(gt=0)  # what the item is worth in its condition (Listing.price_cad)
    new_price_cad: float = Field(gt=0)
    ratio_to_fair: float = Field(gt=0)  # asking / fair
    confidence: Confidence
    confidence_notes: list[str] = Field(default_factory=list)  # why confidence is below high


class ListingDraft(Contract):
    title: str
    description: str
    attributes: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class Listing(Contract):
    item_id: str
    title: str
    description: str
    attributes: dict[str, str]
    tags: list[str]
    condition_grade: Grade
    condition_notes: list[str]
    price_cad: int = Field(gt=0)
    price_justification: list[str]
    preview_images: list[str]
    viewer_url: str | None = None  # 3D viewer, later
    needs_seller_check: bool
    seller_check_reasons: list[str] = Field(default_factory=list)
    deal_rating: DealRating
    highlight: Highlight
