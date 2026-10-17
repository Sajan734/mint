"""Ported from HurayrahB/jev-lab (MIT), splat_diff/judge.py. See buyer_agent/NOTICE.md.

Pure verdict logic. Amendments AM-01..AM-06, AM-21 applied. Thresholds are frozen by
eval/PREREG.md; never change the defaults without a new PREREG version.
"""

import math
from typing import Annotated, get_args

from pydantic import Field, model_validator

from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.models import (
    AlignmentMetrics,
    Category,
    CategoryEvidence,
    Evidence,
    JevViewScores,
    Strict,
    Verdict,
    VerdictCause,
    VerdictLabel,
    ViewFailure,
    unique_labels,
)

CATEGORIES: tuple[Category, ...] = get_args(Category)
DENT_CAVEAT = "Very small dents or scratches may not show up in this check."
ONE_ANGLE = "Seen strongly in one view only, not confirmed."
Frac = Annotated[float, Field(ge=0.5, le=1.0, allow_inf_nan=False)]
Unit = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class Thresholds(Strict):
    viewpoint_min: Unit = 0.5
    min_views: Annotated[int, Field(ge=1, le=12)] = 6
    different: Unit = 0.5
    match_min: Unit = 0.70
    support: Annotated[int, Field(ge=1, le=12)] = 2
    quality_min: Unit = 0.5
    ambiguity_max: Unit = 0.85
    min_answered: Annotated[int, Field(ge=1, le=12)] = 8
    quality_frac: Frac = 0.75
    same_usable_frac: Frac = 0.75

    @model_validator(mode="after")
    def _ordered(self) -> "Thresholds":
        if not 1 <= self.support <= self.min_views <= 12:
            raise ValueError("need 1 <= support <= min_views <= 12")
        return self


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _evidence_for(usable: list[JevViewScores], th: Thresholds) -> dict[Category, CategoryEvidence]:
    out: dict[Category, CategoryEvidence] = {}
    for cat in CATEGORIES:
        values = sorted((getattr(v, cat) for v in usable), reverse=True)
        out[cat] = CategoryEvidence(
            evidence=values[th.support - 1] if len(values) >= th.support else 0.0,
            max=values[0] if values else 0.0,
            views=[v.view for v in usable if getattr(v, cat) >= th.different],
        )
    return out


def _match_score(cats: dict[Category, CategoryEvidence]) -> float:
    """1 - strongest category evidence (support-th highest view). Missing or NaN -> 0.0."""
    top = max((c.evidence for c in cats.values()), default=math.nan)
    return round(1 - top, 6) if math.isfinite(top) else 0.0


def _classify(
    cats: dict[Category, CategoryEvidence], usable: int, answered: int, th: Thresholds
) -> tuple[VerdictLabel, str, list[Category], float, list[str]]:
    """(label, reason, flagged, evidence_score, extra caveats). Same iff match_score >= match_min."""
    match = _match_score(cats)
    flagged = [c for c in CATEGORIES if c != "any_diff" and cats[c].evidence >= th.different]
    caveats: list[str] = []
    if any(c.max >= th.different for c in cats.values()) and not flagged:
        caveats.append(ONE_ANGLE)
    strength = max((cats[c].evidence for c in flagged or CATEGORIES), default=0.0)
    if flagged:
        n = th.support
        where = "one view" if n == 1 else f"at least {n} views"
        return "different", f"Seen in {where}: {', '.join(flagged)}.", flagged, strength, caveats
    if match < th.match_min:
        top = max(cats, key=lambda c: cats[c].evidence)
        reason = f"Not a close enough match (strongest signal: {top} at {cats[top].evidence:.2f})."
        return "different", reason, [], strength, caveats
    if usable < max(th.min_views, math.ceil(th.same_usable_frac * answered)):
        caveats.append("Few views were clear enough to check, so this match is less certain.")
        return (
            "different",
            "Too few views were clear enough to confirm a match.",
            [],
            strength,
            caveats,
        )
    return "same", "No view showed a real difference.", [], match, caveats


def aggregate(
    scores: list[JevViewScores],
    failures: list[ViewFailure],
    requested: int,
    alignment: AlignmentMetrics | None,
    alignment_mode: str,
    th: Thresholds | None = None,
) -> Verdict:
    th = th or Thresholds()
    if alignment_mode not in ("icp", "skipped_view_pairs"):
        raise AgentError(ErrorCode.INPUT_INVALID, f"unknown alignment_mode {alignment_mode!r}")
    unique_labels(s.view for s in scores)
    answered = len(scores)
    if requested < answered + len(failures) or requested < 1:
        raise AgentError(ErrorCode.INPUT_INVALID, "requested < answered + failed")
    if answered < th.min_answered:
        raise AgentError(ErrorCode.JEV_UNAVAILABLE, f"only {answered} views answered")

    quality_ok = [s for s in scores if s.scan_quality_ok >= th.quality_min]
    usable = [s for s in quality_ok if s.viewpoint_match >= th.viewpoint_min]
    cats: dict[Category, CategoryEvidence] = {}
    flagged: list[Category] = []
    extra: list[str] = []
    cause: VerdictCause | None = None
    label: VerdictLabel = "different"
    score = 0.0
    if len(quality_ok) < math.ceil(th.quality_frac * answered):
        cause, reason = "low_quality", "The buyer's scan was too unclear to compare."
    elif len(usable) < th.min_views:
        cause = "misaligned"
        reason = f"Only {len(usable)} of {answered} views looked aligned; rescan and retry."
    else:
        cats = _evidence_for(usable, th)
        label, reason, flagged, score, extra = _classify(cats, len(usable), answered, th)
        if label == "different":
            score = min(1.0, score * len(usable) / requested)
        if alignment and alignment.ambiguity > th.ambiguity_max:
            extra.append("The item looks symmetric, so its orientation may be off.")
    caveats = [DENT_CAVEAT, *extra]
    if failures:
        caveats.append(f"{_plural(len(failures), 'view')} could not be checked.")
    skipped = alignment_mode == "skipped_view_pairs"
    if skipped:
        caveats.append("The two scans were not aligned by us; views were taken as supplied.")
    evidence = Evidence(
        requested_views=requested,
        answered_views=answered,
        usable_views=len(usable),
        failed_views=failures,
        categories=cats,
        flagged=flagged,
        alignment=alignment,
        alignment_mode="skipped_view_pairs" if skipped else "icp",
    )
    return Verdict(
        label=label, evidence_score=score, cause=cause, reason=reason, evidence=evidence,
        caveats=caveats,
    )  # fmt: skip
