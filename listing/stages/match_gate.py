"""match_gate: views + baseline -> MatchCheck (Jev, one request per view; verdict decided in code).

Order: no baseline -> uncertain without asking Jev; fixture stub (raw per-view answers) -> offline;
otherwise every view goes to Jev concurrently with the gate questions from jev_questions.py.
Raw per-view answers are saved to runs/<item>/match_gate_raw.json, in the same format as the fixture
stubs, so thresholds can be re-tuned with scripts/replay_match_gate.py without new API calls.
A mismatch needs a claim (the seller typed the name, or the model is printed on the item): a baseline found by
searching for what identify inferred can be some other product, which says nothing about the seller's item.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient, Image, RetryPolicy, TypeSafeError

from contracts import Baseline, Contract, Identity, MatchCheck, Prob, RunContext, Verdict, View, Views
from images import ImageProblem, fit_for_jev
from jev_questions import GATE_CONTEXT, GATE_QUESTIONS, IMAGE_HEADERS, MODEL, build_state
from stages._fixture import has_stub, load_stub
from stages.baseline_lookup import has_claim
from stages.condition import second_highest
from stages.identify import MissingKeyError

LISTING_ROOT = Path(__file__).resolve().parent.parent

THRESHOLDS = {
    "usable_min": 0.60,  # item_usable P(yes) for a view to count
    "min_usable_views": 6,  # fewer usable views -> uncertain
    "mismatch_below": 0.30,  # either aggregate below this -> mismatch
    "match_min": 0.60,  # same_product aggregate at or above this -> match
}

JEV = {"timeout_s": 30.0, "max_retries": 1}

REASONS = {
    "match": "This scan matches {query}.",
    "different_kind": "This scan doesn't look like {query}. It seems to be a different kind of item.",
    "different_product": (
        "This scan looks like a different model from {query}. Check the product name, "
        "or rescan if the wrong item was captured."
    ),
    "too_few_views": (
        "Too few clear views of the scan to compare with {query}. Please check the listing before publishing."
    ),
    "uncertain": "We couldn't confirm this scan is {query}. Please check the listing before publishing.",
    "unclaimed_different": (
        "The closest reference photo we found for {query} looks like a different product. Add the exact "
        "product name, or check the listing before publishing."
    ),
    "no_baseline": (
        "We couldn't find a reference photo for {query}, so we couldn't check the scan matches it. "
        "Add the exact product name, or check the listing before publishing."
    ),
}


class GateViewAnswer(Contract):
    view_id: str
    item_usable: Prob | None = None
    same_category: Prob | None = None
    same_product: Prob | None = None
    error: str | None = None


class GateRaw(Contract):
    """Raw per-view answers: the fixture stub format and the core of runs/<item>/match_gate_raw.json."""

    views: list[GateViewAnswer]
    query: str | None = None
    baseline_image: str | None = None


def load_raw(data: dict[str, Any]) -> GateRaw:
    """Reads a fixture stub or a saved match_gate_raw.json (which also holds aggregate, verdict, ...)."""
    return GateRaw.model_validate({k: data[k] for k in GateRaw.model_fields if k in data})


@dataclass(frozen=True)
class GateAggregate:
    same_category: float | None
    same_product: float | None
    usable_views: int
    total_views: int


# --- decisions (pure) -------------------------------------------------------------------------


def aggregate(views: list[GateViewAnswer], thresholds: dict[str, Any] = THRESHOLDS) -> GateAggregate:
    usable = [
        v for v in views
        if v.error is None and v.item_usable is not None and v.item_usable >= thresholds["usable_min"]
        and v.same_category is not None and v.same_product is not None
    ]
    if not usable:
        return GateAggregate(None, None, 0, len(views))
    return GateAggregate(
        same_category=statistics.median(v.same_category for v in usable),
        # The baseline shows one side, so only some views face it: the 2nd-highest view decides.
        same_product=second_highest([v.same_product for v in usable]),
        usable_views=len(usable),
        total_views=len(views),
    )


def decide(agg: GateAggregate, thresholds: dict[str, Any] = THRESHOLDS,
           claimed: bool = True) -> tuple[Verdict, str]:
    """Returns (verdict, reason key). Rules apply in order. claimed: the seller typed the product's name or its model
    is printed on it. Without a claim the baseline came from a search we inferred (brand, colour, category), so a
    photo that looks like a different product means the search found the wrong one: uncertain, never a mismatch."""
    if agg.usable_views < thresholds["min_usable_views"]:
        return "uncertain", "too_few_views"
    if agg.same_category < thresholds["mismatch_below"] or agg.same_product < thresholds["mismatch_below"]:
        if not claimed:
            return "uncertain", "unclaimed_different"
        if agg.same_category < thresholds["mismatch_below"]:
            return "mismatch", "different_kind"
        return "mismatch", "different_product"
    if agg.same_product >= thresholds["match_min"]:
        return "match", "match"
    return "uncertain", "uncertain"


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def build_match_check(raw: GateRaw, query: str, thresholds: dict[str, Any] = THRESHOLDS,
                      claimed: bool = True) -> MatchCheck:
    agg = aggregate(raw.views, thresholds)
    verdict, reason_key = decide(agg, thresholds, claimed)
    return MatchCheck(
        same_category=_round(agg.same_category),
        same_product=_round(agg.same_product),
        verdict=verdict,
        reason=REASONS[reason_key].format(query=query),
    )


def no_baseline_check(baseline: Baseline) -> MatchCheck:
    return MatchCheck(
        same_category=None,
        same_product=None,
        verdict="uncertain",
        reason=REASONS["no_baseline"].format(query=baseline.query),
    )


# --- Jev --------------------------------------------------------------------------------------


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else LISTING_ROOT / p


def _jev_key() -> str:
    load_dotenv(LISTING_ROOT.parent / ".env")  # the repo-wide .env
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise MissingKeyError("TYPESAFE_API_KEY is missing: add it to the repo-root .env")
    return key


async def ask_view(jev: AsyncTypeSafeClient, view: View, baseline_image: Image) -> GateViewAnswer:
    try:
        item = Image(fit_for_jev(resolve(view.image_path).read_bytes()).data)
        resp = await jev.system_one(
            state=build_state(GATE_CONTEXT, baseline_image, item),
            questions=GATE_QUESTIONS,
            extra_headers=IMAGE_HEADERS,
        )
    except (TypeSafeError, ImageProblem, OSError) as e:
        return GateViewAnswer(view_id=view.view_id, error=f"{type(e).__name__}: {e}")
    return GateViewAnswer(view_id=view.view_id, **{q: resp.nouls[q].noul for q in GATE_QUESTIONS})


async def ask_jev(views: Views, baseline: Baseline) -> GateRaw:
    _jev_key()
    baseline_image = Image(fit_for_jev(resolve(baseline.image_path).read_bytes()).data)
    async with AsyncTypeSafeClient(
        model=MODEL, timeout=JEV["timeout_s"], retry=RetryPolicy(max_retries=JEV["max_retries"])
    ) as jev:
        answers = await asyncio.gather(*(ask_view(jev, v, baseline_image) for v in views.views))
    failed = sum(a.error is not None for a in answers)
    if failed:
        print(f"[match_gate] {failed} of {len(answers)} views failed", file=sys.stderr)
    return GateRaw(views=list(answers), query=baseline.query, baseline_image=baseline.image_path)


async def match_gate(ctx: RunContext, views: Views, baseline: Baseline, identity: Identity | None = None,
                     seller_name: str | None = None) -> MatchCheck:
    """identity and seller_name say whether the product was claimed (has_claim); without an identity it counts as
    claimed, the strict rules."""
    if baseline.image_path is None:
        return no_baseline_check(baseline)
    claimed = identity is None or has_claim(identity, seller_name)
    if has_stub(ctx, "match_gate"):
        return build_match_check(load_stub(ctx, "match_gate", GateRaw), baseline.query, claimed=claimed)

    raw = await ask_jev(views, baseline)
    check = build_match_check(raw, baseline.query, claimed=claimed)
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    record = raw.model_dump() | {
        "model": MODEL,
        "aggregate": asdict(aggregate(raw.views)),
        "verdict": check.verdict,
        "claimed": claimed,
        "thresholds": THRESHOLDS,
    }
    (ctx.run_dir / "match_gate_raw.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return check
