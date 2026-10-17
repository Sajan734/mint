"""match_gate: views + baseline -> MatchCheck (Jev scores, verdict in code). Stub: fixture scores."""

from __future__ import annotations

from contracts import Baseline, Contract, MatchCheck, Prob, RunContext, Verdict, Views
from stages._fixture import load_stub

THRESHOLDS = {
    "match_min": 0.70,  # both scores at or above -> match
    "mismatch_below": 0.35,  # either score below -> mismatch
}

REASONS = {
    "match": "This scan matches {query}.",
    "mismatch": (
        "This scan doesn't look like {query}. Check the product name, "
        "or rescan if the wrong item was captured."
    ),
    "uncertain": "We couldn't confirm this scan is {query}. Please check the listing before publishing.",
    "no_baseline": (
        "We couldn't find a reference photo for {query}, so we couldn't check the scan matches it. "
        "Add the exact product name, or check the listing before publishing."
    ),
}


class _GateScores(Contract):
    same_category: Prob
    same_product: Prob


def decide_verdict(same_category: float, same_product: float) -> Verdict:
    if min(same_category, same_product) < THRESHOLDS["mismatch_below"]:
        return "mismatch"
    if min(same_category, same_product) >= THRESHOLDS["match_min"]:
        return "match"
    return "uncertain"


def build_match_check(scores: _GateScores, baseline: Baseline) -> MatchCheck:
    verdict = decide_verdict(scores.same_category, scores.same_product)
    return MatchCheck(
        same_category=scores.same_category,
        same_product=scores.same_product,
        verdict=verdict,
        reason=REASONS[verdict].format(query=baseline.query),
    )


def no_baseline_check(baseline: Baseline) -> MatchCheck:
    return MatchCheck(
        same_category=None,
        same_product=None,
        verdict="uncertain",
        reason=REASONS["no_baseline"].format(query=baseline.query),
    )


async def match_gate(ctx: RunContext, views: Views, baseline: Baseline) -> MatchCheck:
    if baseline.image_path is None:
        return no_baseline_check(baseline)
    # TODO: one Jev request per view, aggregate with the 2nd-highest value.
    scores = load_stub(ctx, "match_gate", _GateScores)
    return build_match_check(scores, baseline)
