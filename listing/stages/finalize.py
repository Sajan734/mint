"""finalize: everything -> Listing. The price is computed here, in code."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from contracts import (
    Condition,
    Defect,
    Grade,
    Listing,
    ListingDraft,
    MatchCheck,
    ReferencePrice,
    RunContext,
    Views,
)

# Placeholder factors, to be tuned against real outputs.
PRICE = {
    "basis_factor": {"new_retail": 0.70, "used_comps": 1.00, "llm_estimate": 0.70},
    "grade_factor": {"like_new": 1.00, "light_wear": 0.90, "moderate_wear": 0.75, "heavy_wear": 0.55},
    "min_price_cad": 5,
}

DEFECT_NOTE_MIN = 0.60  # defects scored below this are left out of buyer notes

DEFECT_PHRASES = {
    "scratch": "Scratch",
    "scuff": "Scuff",
    "dent": "Dent",
    "crack": "Crack",
    "stain": "Stain",
    "discoloration": "Discolouration",
    "wear": "Signs of wear",
    "missing_part": "Missing part",
    "other": "Other mark",
}

NO_DEFECTS_NOTE = "No notable defects found."

BASIS_LABELS = {"new_retail": "new retail", "used_comps": "used sales", "llm_estimate": "estimate"}
GRADE_LABELS = {
    "like_new": "like new",
    "light_wear": "light wear",
    "moderate_wear": "moderate wear",
    "heavy_wear": "heavy wear",
}

PREVIEW_VIEW_IDS = ["v00", "v02", "v04", "v06"]  # front, right, back, left at the low ring

CONDITION_CHECK_REASON = "Condition needs a quick check before publishing."


def compute_price(reference: ReferencePrice, grade: Grade) -> tuple[int, list[str]]:
    basis_factor = PRICE["basis_factor"][reference.basis]
    grade_factor = PRICE["grade_factor"][grade]
    raw = Decimal(str(reference.amount_cad)) * Decimal(str(basis_factor)) * Decimal(str(grade_factor))
    price = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    price = max(price, PRICE["min_price_cad"])
    lines = [
        f"Reference: ${reference.amount_cad:,.2f} CAD ({BASIS_LABELS[reference.basis]}). {reference.note}",
        f"Basis adjustment ({BASIS_LABELS[reference.basis]}): x{basis_factor:.2f}",
        f"Condition ({GRADE_LABELS[grade]}): x{grade_factor:.2f}",
        f"Asking price: ${price:,} CAD",
    ]
    return price, lines


def build_notes(defects: list[Defect]) -> list[str]:
    shown = sorted((d for d in defects if d.score >= DEFECT_NOTE_MIN), key=lambda d: -d.score)
    notes = []
    for d in shown:
        n = len(d.view_ids)
        notes.append(f"{DEFECT_PHRASES[d.kind]} (seen in {n} view{'' if n == 1 else 's'})")
    return notes or [NO_DEFECTS_NOTE]


def pick_previews(views: Views) -> list[str]:
    by_id = {v.view_id: v.image_path for v in views.views}
    previews = [by_id[i] for i in PREVIEW_VIEW_IDS if i in by_id]
    return previews or [v.image_path for v in views.views[: len(PREVIEW_VIEW_IDS)]]


def seller_check_reasons(match: MatchCheck, condition: Condition) -> list[str]:
    reasons = []
    if match.verdict == "uncertain":
        reasons.append(match.reason)
    if condition.needs_seller_check:
        reasons.append(CONDITION_CHECK_REASON)
    return reasons


def build_listing(
    views: Views,
    match: MatchCheck,
    draft: ListingDraft,
    reference: ReferencePrice,
    condition: Condition,
) -> Listing:
    price, justification = compute_price(reference, condition.grade)
    reasons = seller_check_reasons(match, condition)
    return Listing(
        item_id=views.item_id,
        title=draft.title,
        description=draft.description,
        attributes=draft.attributes,
        tags=draft.tags,
        condition_grade=condition.grade,
        condition_notes=build_notes(condition.defects),
        price_cad=price,
        price_justification=justification,
        preview_images=pick_previews(views),
        needs_seller_check=bool(reasons),
        seller_check_reasons=reasons,
    )


async def finalize(
    ctx: RunContext,
    views: Views,
    match: MatchCheck,
    draft: ListingDraft,
    reference: ReferencePrice,
    condition: Condition,
) -> Listing:
    return build_listing(views, match, draft, reference, condition)
