"""Contracts for the listing pipeline. Source of truth for every stage's inputs and outputs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Prob = Annotated[float, Field(ge=0.0, le=1.0)]

Grade = Literal["like_new", "light_wear", "moderate_wear", "heavy_wear"]
Verdict = Literal["match", "mismatch", "uncertain"]
Specificity = Literal["model", "brand", "type"]  # how specific the identification could honestly be
PriceBasis = Literal["new_retail", "used_comps", "llm_estimate"]
DefectKind = Literal[
    "scratch", "scuff", "dent", "crack", "stain", "discoloration", "wear", "missing_part", "other"
]
DealLabel = Literal["great", "good", "fair", "high", "overpriced"]
Confidence = Literal["high", "medium", "low"]


def _normalise(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _words(text: str) -> tuple[str, set[int], set[int]]:
    """The text without case, spaces or punctuation, and where its words start and end in that string."""
    flat, starts, ends = "", set(), set()
    for word in re.findall(r"[^\W_]+", text.casefold()):
        starts.add(len(flat))
        flat += word
        ends.add(len(flat))
    return flat, starts, ends


def backed_by_text(value: str, visible_text: list[str]) -> bool:
    """True if `value` appears in some visible text as whole words, ignoring case, spaces and punctuation:
    "WH1000XM4" is in "WH-1000XM4", but "MX Master 3" is not in "MX Master 3S" (that's another model)."""
    needle = _normalise(value)
    if not needle:
        return False
    for text in visible_text:
        flat, starts, ends = _words(text)
        i = flat.find(needle)
        while i != -1:
            if i in starts and i + len(needle) in ends:
                return True
            i = flat.find(needle, i + 1)
    return False


def product_name(brand: str | None, model: str | None, category: str) -> str:
    """How a listing names the product: brand and model ("Logitech MX Master 3S"), else brand and type."""
    if model:
        return model if brand and backed_by_text(brand, [model]) else f"{brand} {model}" if brand else model
    return f"{brand} {category}" if brand else category


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


class View(Contract):
    """One photo of the item, resized for the models that read it."""

    view_id: str  # p01, p02, ...
    label: str  # "photo 1", ...
    image_path: str  # relative to listing/
    source_url: str | None = None  # a public URL of the same photo, when the input gave one (used for Lens)


class Views(Contract):
    item_id: str
    views: list[View] = Field(min_length=1)


class Identity(Contract):
    """What the item is, as specific as the evidence allows. identify decides brand and model in code from what was
    read off the item, the seller's name and Lens matches (`evidence` says which backed each)."""

    category: str  # the specific product type, e.g. "wireless mouse"
    brand: str | None = None
    model: str | None = None
    visible_text: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    product_name: str  # the most specific supported name: "Logitech MX Master 3S" / "Logitech wireless mouse"
    specificity: Specificity
    evidence: list[str] = Field(default_factory=list)  # what backed the brand and model, for people checking
    search_query: str
    confidence: Prob

    @model_validator(mode="before")
    @classmethod
    def _derive_name_and_specificity(cls, data: Any) -> Any:
        """specificity and product_name follow from brand, model and category when a caller leaves them out."""
        if isinstance(data, dict):
            data = dict(data)
            brand, model = data.get("brand"), data.get("model")
            data.setdefault("specificity", "model" if model else "brand" if brand else "type")
            data.setdefault("product_name", product_name(brand, model, data.get("category") or ""))
        return data

    @model_validator(mode="after")
    def _specificity_matches_fields(self) -> Identity:
        expected = "model" if self.model else "brand" if self.brand else "type"
        if self.model and not self.brand:
            raise ValueError("a model needs a brand")
        if self.specificity != expected:
            raise ValueError(f"specificity {self.specificity!r} doesn't fit brand {self.brand!r}, model {self.model!r}")
        return self


class IdentityCandidate(Contract):
    """Gemini's best reading of what the product is, from all the evidence; code decides what is claimed."""

    brand: str | None = None
    model: str | None = None  # the model name or number, without the brand
    product_type: str  # specific, e.g. "wireless mouse", "over-ear headphones"


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


class PriceSource(Contract):
    """A real listing of the product new, that the reference price was worked out from."""

    title: str  # as the listing names the product
    seller: str | None = None
    price_cad: float = Field(gt=0)
    url: str | None = None


class PriceResultCheck(Contract):
    """Gemini's reading of one numbered shopping result: is it this product, sold new on its own?"""

    index: int = Field(ge=0)
    same_product: Prob  # the item's product: its model if known, else anything that fits what is known
    new_single_unit: bool  # sold new, as one unit: not used, refurbished, a bundle, a multipack or an accessory


class ReferencePrice(Contract):
    amount_cad: float = Field(gt=0)
    basis: PriceBasis
    note: str
    sources: list[PriceSource] = Field(default_factory=list)  # the listings behind a looked-up price
    exact_model: bool = True  # False: listings of the brand's line of this product, since the exact model isn't known


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
    price_sources: list[PriceSource] = Field(default_factory=list)  # listings the new price came from, if looked up
    preview_images: list[str]
    needs_seller_check: bool
    seller_check_reasons: list[str] = Field(default_factory=list)
    deal_rating: DealRating
