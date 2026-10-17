"""deal_rating: the asking price vs what the item is worth in its condition -> DealRating (pure code, no API).

The fair price F is finalize's price for this item in this condition (compute_price: new price x grade factor x
defect penalties), so the rating and Listing.price_cad always agree. A big discount from new doesn't make a good
deal on its own: the asking price A is judged against F, which already counts what the wear and damage cost.
Without an asking price (input.json asking_price_cad, --asking-price) Mint's suggested price, F itself, is rated.

Weak inputs (a new price that wasn't looked up, an unconfirmed match, no reference photo, a condition that needs a
seller check) widen F into the range F x (1 - u) .. F x (1 + u). A below-fair label must hold against the bottom of
that range and an above-fair label against its top, so shaky numbers pull the rating toward fair rather than
claiming a great deal or an overpriced item.
"""

from __future__ import annotations

import math
from typing import Any

from contracts import Baseline, Condition, DealRating, MatchCheck, ReferencePrice, RunContext
from stages.finalize import compute_price, join_words, price_factors
from stages.reference_price import is_category_default

DEAL = {
    # Upper bounds of asking / fair for each label: the buyer site's price badge (buyer/lib/price-badge.ts:
    # great <= 0.85, fair <= 1.10, high <= 1.30) with "good" split out of its fair band.
    "bands": [(0.85, "great"), (0.95, "good"), (1.10, "fair"), (1.30, "high"), (math.inf, "overpriced")],
    # Share of F either side added for each weak input. A category default replaces llm_estimate.
    "uncertainty": {
        "llm_estimate": 0.20,
        "category_default": 0.35,
        "match_uncertain": 0.15,
        "no_baseline": 0.10,
        "condition_check": 0.10,
    },
    "max_uncertainty": 0.60,
    "confidence": [(0.0, "high"), (0.25, "medium"), (math.inf, "low")],  # upper bounds of the uncertainty
    "about_same_pct": 3,  # an asking price within this % of F is "about what it's worth"
}

BELOW_FAIR = ("great", "good")
ABOVE_FAIR = ("high", "overpriced")

CONFIDENCE_NOTES = {
    "llm_estimate": "the new price is a model estimate, not looked up",
    "category_default": "the new price is a rough default for this kind of item, not looked up",
    "match_uncertain": "we couldn't confirm the scan is this exact product",
    "no_baseline": "the condition was judged without a reference photo",
    "condition_check": "the condition needs a check by the seller",
}

HEADLINES = {
    "great": "Great deal.",
    "good": "Good deal.",
    "fair": "Fair price.",
    "high": "A bit high.",
    "overpriced": "Overpriced for its condition.",
}
LABEL_WORDS = {
    "great": "a great deal",
    "good": "a good deal",
    "fair": "a fair price",
    "high": "a bit high",
    "overpriced": "overpriced",
}
CONDITION_PHRASES = {
    "like_new": "in like-new condition",
    "light_wear": "with light wear",
    "moderate_wear": "with moderate wear",
    "heavy_wear": "with heavy wear",
}


def asking_price(value: Any) -> float | None:
    """A seller's asking price from input.json or the CLI: a positive number of dollars, or None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"asking_price_cad must be a positive number of Canadian dollars, got {value!r}")
    return float(value)


# --- decisions (pure) -------------------------------------------------------------------------


def uncertainty(
    reference: ReferencePrice, condition: Condition, match: MatchCheck, baseline: Baseline
) -> tuple[float, list[str]]:
    """Returns (u, the weak inputs behind it)."""
    weak = []
    if is_category_default(reference):
        weak.append("category_default")
    elif reference.basis == "llm_estimate":
        weak.append("llm_estimate")
    if match.verdict == "uncertain":
        weak.append("match_uncertain")
    if baseline.image_path is None:
        weak.append("no_baseline")
    if condition.needs_seller_check:
        weak.append("condition_check")
    u = min(sum(DEAL["uncertainty"][w] for w in weak), DEAL["max_uncertainty"])
    return round(u, 3), weak


def band(ratio: float) -> str:
    return next(label for upper, label in DEAL["bands"] if ratio <= upper)


def rate(asking: float, fair: float, u: float) -> tuple[str, str]:
    """Returns (rating, the rating on the numbers alone). A below-fair rating must hold even if F is as low as
    F x (1 - u), an above-fair one even if F is as high as F x (1 + u); anything else is fair."""
    alone = band(asking / fair)
    if (below := band(asking / (fair * (1 - u)))) in BELOW_FAIR:
        return below, alone
    if (above := band(asking / (fair * (1 + u)))) in ABOVE_FAIR:
        return above, alone
    return "fair", alone


def confidence_for(u: float) -> str:
    return next(label for upper, label in DEAL["confidence"] if u <= upper)


# --- explanation ------------------------------------------------------------------------------


def dollars(amount: float) -> str:
    return f"${amount:,.0f}" if amount == round(amount) else f"${amount:,.2f}"


def percent(share: float) -> str:
    return f"{round(abs(share) * 100)}%"


def condition_phrase(condition: Condition) -> str:
    """"with light wear", "in like-new condition with a crack or tear": the grade and the priced defects."""
    phrase = CONDITION_PHRASES[condition.grade]
    defects = [label for label, _ in price_factors(condition)[1:]]
    if not defects:
        return phrase
    return f"{phrase}{' and ' if phrase.startswith('with') else ' with '}{join_words(defects)}"


def against_new(amount: float, new: float) -> str:
    share = 1 - amount / new
    if round(share * 100) == 0:
        return f"about the new price of {dollars(round(new))}"
    side = "below" if share > 0 else "above"
    return f"{percent(share)} {side} the new price of about {dollars(round(new))}"


def against_fair(asking: float, fair: int, new: float) -> str:
    ratio = asking / fair
    if abs(ratio - 1) * 100 <= DEAL["about_same_pct"]:
        if asking < new:
            return f"the {percent(1 - asking / new)} discount is about what its condition costs"
        return "the asking price is about what it's worth in this condition"
    side = "below" if ratio < 1 else "above"
    return f"the asking price is {percent(ratio - 1)} {side} what it's worth in this condition"


def explain(rating: str, alone: str, asking: float, source: str, fair: int, new: float, condition: Condition,
            u: float, notes: list[str]) -> str:
    phrase = condition_phrase(condition)
    expected = f"{phrase[0].upper()}{phrase[1:]} we'd expect about {dollars(fair)}"
    sentences = [HEADLINES[rating]]
    if source == "suggested":
        sentences.append(f"No asking price was given, so this rates Mint's suggested price of {dollars(fair)}.")
        sentences.append(f"{expected}, {against_new(fair, new)}.")
    else:
        sentences.append(f"Asking {dollars(asking)} is {against_new(asking, new)}.")
        below_new = 1 - fair / new
        sentences.append(f"{expected} ({percent(below_new)} {'below' if below_new >= 0 else 'above'} new), "
                         f"so {against_fair(asking, fair, new)}.")
    if notes:
        sentences.append(f"Less certain because {join_words(notes)}.")
    if rating != alone:
        sentences.append(
            f"On these numbers alone it would be {LABEL_WORDS[alone]}, but its fair price could be anywhere from "
            f"{dollars(round(fair * (1 - u)))} to {dollars(round(fair * (1 + u)))}."
        )
    return " ".join(sentences)


def rate_deal(
    reference: ReferencePrice,
    condition: Condition,
    match: MatchCheck,
    baseline: Baseline,
    asking_price_cad: float | None,
) -> DealRating:
    fair, _ = compute_price(reference, condition)
    source = "seller" if asking_price_cad is not None else "suggested"
    asking = round(asking_price_cad, 2) if asking_price_cad is not None else float(fair)
    u, weak = uncertainty(reference, condition, match, baseline)
    rating, alone = rate(asking, fair, u)
    notes = [CONFIDENCE_NOTES[w] for w in weak]
    return DealRating(
        rating=rating,
        explanation=explain(rating, alone, asking, source, fair, reference.amount_cad, condition, u, notes),
        asking_price_cad=asking,
        asking_price_source=source,
        fair_price_cad=fair,
        new_price_cad=reference.amount_cad,
        ratio_to_fair=round(asking / fair, 3),
        confidence=confidence_for(u),
        confidence_notes=notes,
    )


async def deal_rating(
    ctx: RunContext,
    reference: ReferencePrice,
    condition: Condition,
    match: MatchCheck,
    baseline: Baseline,
    asking_price_cad: float | None = None,
) -> DealRating:
    return rate_deal(reference, condition, match, baseline, asking_price_cad)
