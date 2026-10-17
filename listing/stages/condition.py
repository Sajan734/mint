"""condition: views + baseline -> Condition (Jev, one request per view).

Fixture items that have stubs/condition.json stay offline. Otherwise every view goes to Jev concurrently.
With a baseline photo the questions compare against it; with no baseline (image_path is None) the
no-baseline questions run on the views alone, so pricing still works.
Per question, answers are aggregated across usable views with the 2nd-highest value, so one noisy view
can't decide a result. Code maps the aggregates to a grade, defects and the seller-check flag.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient, Image, RetryPolicy, TypeSafeError

from contracts import Baseline, Condition, Defect, RunContext, View, Views
from images import ImageProblem, fit_for_jev
from jev_questions import (
    CONDITION_CONTEXT,
    CONDITION_CONTEXT_NO_BASELINE,
    CONDITION_QUESTIONS,
    CONDITION_QUESTIONS_NO_BASELINE,
    IMAGE_HEADERS,
    MODEL,
    WEAR_LEVELS,
)
from stages._fixture import has_stub, load_stub
from stages.identify import MissingKeyError

LISTING_ROOT = Path(__file__).resolve().parent.parent

JEV = {"timeout_s": 30.0, "max_retries": 1}

USABLE = {
    "view_min": 0.60,  # item_usable P(yes) for a view to count
    "min_views": 6,  # fewer usable views than this -> seller check
}

# Upper bounds of the aggregated wear score (0 = like new .. 3 = heavy wear) for each grade.
GRADE_BANDS = [(0.5, "like_new"), (1.5, "light_wear"), (2.5, "moderate_wear"), (math.inf, "heavy_wear")]

DEFECTS = {
    "report_min": 0.35,  # aggregated P(yes) to list a defect (finalize decides what buyers see)
    "view_min": 0.60,  # per-view P(yes) for a view to be listed as showing the defect
    "unsure_low": 0.40,  # aggregated values in [unsure_low, unsure_high) -> seller check
    "unsure_high": 0.70,
}

GRADE_CHECK = {"confidence_min": 0.50}  # mean Score confidence below this -> seller check

DEFECT_KINDS = {
    "scratches_scuffs": "scratch",
    "stains_discolouration": "stain",
    "cracks_tears": "crack",
    "missing_broken": "missing_part",
}


@dataclass
class ViewAnswers:
    view_id: str
    nouls: dict[str, float] = field(default_factory=dict)
    wear_score: float | None = None
    wear_probs: dict[int, float] = field(default_factory=dict)
    wear_confidence: float | None = None
    error: str | None = None


def second_highest(values: list[float]) -> float:
    ordered = sorted(values, reverse=True)
    return ordered[1] if len(ordered) > 1 else ordered[0]


def grade_for(wear_score: float) -> str:
    return next(grade for upper, grade in GRADE_BANDS if wear_score < upper)


def build_condition(answers: list[ViewAnswers]) -> tuple[Condition, list[str]]:
    """Pure: per-view Jev answers -> Condition, plus the reasons a seller check is needed."""
    answered = [a for a in answers if a.error is None]
    if not answered:
        raise RuntimeError("Jev answered none of the views; condition can't be judged")
    usable = [a for a in answered if a.nouls["item_usable"] >= USABLE["view_min"]]
    pool = usable or answered  # judge from every answered view rather than nothing; flagged below
    reasons = []
    if len(usable) < USABLE["min_views"]:
        reasons.append(f"only {len(usable)} of {len(answers)} views were usable")

    wear = second_highest([a.wear_score for a in pool])
    grade = grade_for(wear)
    level = WEAR_LEVELS.index(grade)
    grade_score = statistics.fmean(a.wear_probs.get(level, 0.0) for a in pool)
    grade_confidence = statistics.fmean(a.wear_confidence for a in pool)
    if grade_confidence < GRADE_CHECK["confidence_min"]:
        reasons.append(f"wear grade confidence is low ({grade_confidence:.2f})")

    defects = []
    for question, kind in DEFECT_KINDS.items():
        score = second_highest([a.nouls[question] for a in pool])
        if DEFECTS["unsure_low"] <= score < DEFECTS["unsure_high"]:
            reasons.append(f"unsure about {question} ({score:.2f})")
        if score >= DEFECTS["report_min"]:
            view_ids = [a.view_id for a in pool if a.nouls[question] >= DEFECTS["view_min"]]
            defects.append(Defect(kind=kind, score=round(score, 3), view_ids=view_ids))

    condition = Condition(
        grade=grade,
        grade_score=round(grade_score, 3),
        grade_confidence=round(grade_confidence, 3),
        defects=defects,
        usable_view_count=len(usable),
        needs_seller_check=bool(reasons),
    )
    return condition, reasons


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else LISTING_ROOT / p


def _jev_key() -> str:
    load_dotenv(LISTING_ROOT / ".env")
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise MissingKeyError("TYPESAFE_API_KEY is missing: add it to listing/.env")
    return key


async def ask_view(
    jev: AsyncTypeSafeClient, view: View, context: str, questions: dict, baseline_image: Image | None
) -> ViewAnswers:
    try:
        state = {"context": context, "item": Image(fit_for_jev(resolve(view.image_path).read_bytes()).data)}
        if baseline_image is not None:
            state["baseline"] = baseline_image
        resp = await jev.system_one(state=state, questions=questions, extra_headers=IMAGE_HEADERS)
    except (TypeSafeError, ImageProblem, OSError) as e:
        return ViewAnswers(view.view_id, error=f"{type(e).__name__}: {e}")
    wear = resp.scores["wear"]
    return ViewAnswers(
        view_id=view.view_id,
        nouls={q: resp.nouls[q].noul for q in questions if q != "wear"},
        wear_score=wear.score,
        wear_probs=dict(wear.probabilities),
        wear_confidence=wear.confidence,
    )


async def condition(ctx: RunContext, views: Views, baseline: Baseline) -> Condition:
    if has_stub(ctx, "condition"):
        return load_stub(ctx, "condition", Condition)
    _jev_key()
    use_baseline = baseline.image_path is not None
    baseline_image = Image(fit_for_jev(resolve(baseline.image_path).read_bytes()).data) if use_baseline else None
    context, questions = (
        (CONDITION_CONTEXT, CONDITION_QUESTIONS) if use_baseline else (CONDITION_CONTEXT_NO_BASELINE, CONDITION_QUESTIONS_NO_BASELINE)
    )
    async with AsyncTypeSafeClient(
        model=MODEL, timeout=JEV["timeout_s"], retry=RetryPolicy(max_retries=JEV["max_retries"])
    ) as jev:
        answers = await asyncio.gather(*(ask_view(jev, v, context, questions, baseline_image) for v in views.views))
    result, reasons = build_condition(list(answers))
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    (ctx.run_dir / "condition_raw.json").write_text(
        json.dumps(
            {"baseline_used": use_baseline, "seller_check_reasons": reasons, "views": [asdict(a) for a in answers]},
            indent=2,
        ),
        encoding="utf-8",
    )
    return result
