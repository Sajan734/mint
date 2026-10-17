"""finalize: everything -> Listing. The price is computed here, in code.

Price = reference price x condition factor x (1 - penalty) per priced defect, rounded to the nearest $5,
never below the floor. The same factors feed the justification sentence, so it always shows the real numbers.
The deal rating (stages/deal_rating.py, built on this same price) and the highlight are carried through as they are.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from contracts import (
    Baseline,
    Condition,
    DealRating,
    Defect,
    Highlight,
    Listing,
    ListingDraft,
    MatchCheck,
    ReferencePrice,
    RunContext,
    View,
    Views,
)

# Starting values, to be tuned against real outputs. Defect kinds without a penalty aren't priced.
PRICE = {
    "grade_factor": {"like_new": 0.80, "light_wear": 0.65, "moderate_wear": 0.50, "heavy_wear": 0.30},
    "defect_penalty": {"missing_part": 0.25, "crack": 0.15, "stain": 0.08, "scratch": 0.05},
    "defect_min_score": 0.60,  # defects scored below this are neither noted nor priced
    "round_to_cad": 5,
    "floor_cad": 5,
}

GRADE_LABELS = {
    "like_new": "like new",
    "light_wear": "light wear",
    "moderate_wear": "moderate wear",
    "heavy_wear": "heavy wear",
}

# What Jev was asked about for each kind condition reports, so notes don't claim more than was checked.
DEFECT_NOUNS = {
    "scratch": "scratches or scuffs",
    "scuff": "a scuff",
    "dent": "a dent",
    "crack": "a crack or tear",
    "stain": "stains or discolouration",
    "discoloration": "discolouration",
    "wear": "signs of wear",
    "missing_part": "a missing or broken part",
    "other": "a mark",
}

REFERENCE_OPENINGS = {
    "new_retail": "We estimate the new price at about ${amount:,.2f}",
    "used_comps": "We estimate the used market price at about ${amount:,.2f}",
    "llm_estimate": "Our rough estimate of the new price is about ${amount:,.2f}",
}

PREVIEW_VIEW_IDS = ["v00", "v02", "v04", "v06"]  # front, right, back, left on the low ring

NO_DEFECTS_NOTE = "No defects stood out in any view."
NO_BASELINE_REASON = "We found no reference photo of this product, so condition was judged from the scan alone."
CONDITION_CHECK_REASON = "Condition needs a quick check before publishing."

Factor = tuple[str, Decimal]  # (what it's for, multiplier)


def views_by_id(views: Views, view_ids: list[str]) -> list[View]:
    by_id = {v.view_id: v for v in views.views}
    missing = [i for i in view_ids if i not in by_id]
    if missing:
        raise ValueError(f"no rendered view with id {', '.join(missing)}; rendered: {', '.join(by_id)}")
    return [by_id[i] for i in view_ids]


def noted_defects(defects: list[Defect]) -> list[Defect]:
    """Defects confident enough to show buyers and to price, most confident first."""
    return sorted((d for d in defects if d.score >= PRICE["defect_min_score"]), key=lambda d: -d.score)


def defect_note(defect: Defect, views: Views) -> str:
    noun = DEFECT_NOUNS[defect.kind]
    labels = [v.label for v in views_by_id(views, defect.view_ids)]
    if not labels:
        return f"The condition check found {noun}, but no single view shows it clearly."
    if len(labels) == 1:
        return f"The {labels[0]} view shows {noun}."
    return f"{len(labels)} views show {noun}: {'; '.join(labels)}."


def build_notes(defects: list[Defect], views: Views) -> list[str]:
    return [defect_note(d, views) for d in noted_defects(defects)] or [NO_DEFECTS_NOTE]


def price_factors(condition: Condition) -> list[Factor]:
    factors = [(GRADE_LABELS[condition.grade], Decimal(str(PRICE["grade_factor"][condition.grade])))]
    for d in noted_defects(condition.defects):
        penalty = PRICE["defect_penalty"].get(d.kind)
        if penalty is not None:
            factors.append((DEFECT_NOUNS[d.kind], 1 - Decimal(str(penalty))))
    return factors


def round_price(raw: Decimal) -> int:
    step = Decimal(PRICE["round_to_cad"])
    rounded = int((raw / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step)
    return max(rounded, PRICE["floor_cad"])


def join_words(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def justify_price(reference: ReferencePrice, factors: list[Factor], raw: Decimal, price: int) -> str:
    opening = REFERENCE_OPENINGS[reference.basis].format(amount=reference.amount_cad)
    steps = join_words([f"x {factor:.2f} for {label}" for label, factor in factors])
    if price == PRICE["floor_cad"] and raw < price:
        ending = f"which is below our ${price} minimum, so it's listed at ${price}"
    else:
        ending = f"rounded to ${price}"
    return f"{opening}; {steps} gives ${raw:,.2f}, {ending}."


def compute_price(reference: ReferencePrice, condition: Condition) -> tuple[int, str]:
    """Returns (price in CAD, the one-sentence justification)."""
    factors = price_factors(condition)
    raw = Decimal(str(reference.amount_cad))
    for _, factor in factors:
        raw *= factor
    price = round_price(raw)
    return price, justify_price(reference, factors, raw, price)


def pick_previews(views: Views) -> list[str]:
    return [v.image_path for v in views_by_id(views, PREVIEW_VIEW_IDS)]


def seller_check_reasons(match: MatchCheck, baseline: Baseline, condition: Condition) -> list[str]:
    reasons = []
    if match.verdict == "uncertain":
        reasons.append(match.reason)
    if baseline.image_path is None:
        reasons.append(NO_BASELINE_REASON)
    if condition.needs_seller_check:
        reasons.append(CONDITION_CHECK_REASON)
    return reasons


def build_listing(
    views: Views,
    match: MatchCheck,
    baseline: Baseline,
    draft: ListingDraft,
    reference: ReferencePrice,
    condition: Condition,
    deal_rating: DealRating,
    highlight: Highlight,
) -> Listing:
    price, justification = compute_price(reference, condition)
    reasons = seller_check_reasons(match, baseline, condition)
    return Listing(
        item_id=views.item_id,
        title=draft.title,
        description=draft.description,
        attributes=draft.attributes,
        tags=draft.tags,
        condition_grade=condition.grade,
        condition_notes=build_notes(condition.defects, views),
        price_cad=price,
        price_justification=[justification],
        preview_images=pick_previews(views),
        needs_seller_check=bool(reasons),
        seller_check_reasons=reasons,
        deal_rating=deal_rating,
        highlight=highlight,
    )


async def finalize(
    ctx: RunContext,
    views: Views,
    match: MatchCheck,
    baseline: Baseline,
    draft: ListingDraft,
    reference: ReferencePrice,
    condition: Condition,
    deal_rating: DealRating,
    highlight: Highlight,
) -> Listing:
    return build_listing(views, match, baseline, draft, reference, condition, deal_rating, highlight)
