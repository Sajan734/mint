"""Compare pipeline (U24). Order is fixed by AM-08:
resolve -> judge -> aggregate -> check_claims -> plan(PRE-claims verdict) -> apply_claims -> advise.
"""

import asyncio
import dataclasses
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from buyer_agent import sources
from buyer_agent.advisor import draft, template_step
from buyer_agent.aggregate import DENT_CAVEAT, aggregate
from buyer_agent.claims import (
    MIN_USABLE_VIEWS,
    ClaimsProvider,
    apply_claims,
    check_claims,
    resolve_claims,
    usable_labels,
)
from buyer_agent.config import Settings
from buyer_agent.errors import AgentError, ErrorCode, user_message
from buyer_agent.explain import build_explanation
from buyer_agent.groq_client import GroqAnswer, GroqClient
from buyer_agent.images import check_request_bytes, thumbnail_png
from buyer_agent.jev_client import JevAnswer, JevClient
from buyer_agent.judge import judge_views
from buyer_agent.models import (
    ClaimsFinding,
    CompareRequest,
    CompareResponse,
    ErrorInfo,
    Evidence,
    JevViewScores,
    ListingClaims,
    Verdict,
    ViewPair,
)
from buyer_agent.planner import plan
from buyer_agent.runlog import RunLog, safe_exc

log = logging.getLogger(__name__)
UNVALIDATED_CAVEAT = "Rendered with an unvalidated renderer; treat this result as a preview."
NO_CLAIMS_CAVEAT = "No listing details were available, so the item was not checked against them."
CLAIMS_FAILED_CAVEAT = "The listing details could not be checked."
FEW_VIEWS_CAVEAT = "Too few clear views to check the listing details."
THUMB_SIDE = 512
REJECTED_REASON = "The listing's scan does not match the product it describes."


_RESOLVE_GATE = threading.Semaphore(1)  # a resolve thread outlives its timeout; never overlap two


def _gated_resolve(resolver: Callable[..., sources.Resolved], *args: Any) -> sources.Resolved:
    with _RESOLVE_GATE:
        return resolver(*args)


@dataclass(frozen=True)
class Deps:
    settings: Settings
    jev: JevClient
    groq: GroqClient
    renderer: Any
    runlog_factory: Callable[[str], RunLog]
    claims_provider: ClaimsProvider | None = None
    resolver: Callable[..., sources.Resolved] = sources.resolve
    clock: Callable[[], float] = time.monotonic


@dataclass
class _Ctx:
    req: CompareRequest
    deps: Deps
    run: RunLog
    t0: float
    timings: dict[str, int] = field(default_factory=dict)

    def remaining_s(self) -> float:
        """Request time left under request_cap_s (never negative)."""
        return max(0.0, self.deps.settings.request_cap_s - (self.deps.clock() - self.t0))

    def lap(self, name: str, start: float) -> None:
        self.timings[name] = int((self.deps.clock() - start) * 1000)


class _RecordingGroq:
    """Wraps a Groq client so the run folder gets every call (groq.json)."""

    def __init__(self, inner: GroqClient) -> None:
        self._inner = inner
        self.records: list[dict[str, str]] = []

    async def chat(self, model: str, system: str, user: str, *, key: str = "") -> GroqAnswer:
        answer = await self._inner.chat(model, system, user, key=key)
        self.records.append({"model": answer.model, "text": answer.text, "key": key})
        return answer


def _quality_verdict(issues: tuple[str, ...]) -> Verdict:
    evidence = Evidence(
        requested_views=0, answered_views=0, usable_views=0, failed_views=[], categories={},
        flagged=[], alignment=None, alignment_mode="icp",
    )  # fmt: skip
    return Verdict(
        label="different",
        cause="low_quality",
        evidence_score=0.0,
        reason="The scans were too incomplete or too different in size to compare.",
        evidence=evidence,
        caveats=[DENT_CAVEAT],
    )


def _failed(ctx: _Ctx, code: ErrorCode) -> CompareResponse:
    ctx.lap("total", ctx.t0)
    return CompareResponse(
        comparison_id=ctx.req.comparison_id, status="failed", verdict=None,
        claims_available=False, claims_findings=[], next_step=None,
        error=ErrorInfo(code=code.value, message=user_message(code)),
        model_ids={}, timings_ms=ctx.timings, run_id=str(ctx.req.comparison_id),
    )  # fmt: skip


def _quiet(label: str, fn: Callable[..., Any], *args: Any) -> None:
    """Run-log writes are best effort: a disk error never fails a request (M2)."""
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 the verdict matters more than its log
        log.warning("run log write failed (%s): %s", label, safe_exc(exc))


def _save_pairs(run: RunLog, pairs: list[ViewPair]) -> None:
    """Thumbnails only (<= THUMB_SIDE px), so a run folder stays small (S-M4)."""
    for i, p in enumerate(pairs):
        for name, data in ((f"a_{i:02d}.png", p.png_a), (f"b_{i:02d}.png", p.png_b)):
            _quiet(name, lambda n=name, d=data: run.save_png(n, thumbnail_png(d, THUMB_SIDE)))


async def _judge(ctx: _Ctx, pairs: list[ViewPair]) -> tuple[list[JevViewScores], list]:
    index = {p.label: i for i, p in enumerate(pairs)}

    def on_raw(label: str, answer: JevAnswer) -> None:
        _quiet("jev", ctx.run.save_json, f"jev/view_{index[label]:02d}.json",
               {"view": label, **dataclasses.asdict(answer)})  # fmt: skip

    def on_failure(label: str, code: str, detail: str) -> None:
        _quiet("failure", ctx.run.save_failure_detail, label, f"{code}: {detail}")

    return await judge_views(ctx.deps.jev, pairs, ctx.deps.settings, on_raw, on_failure)


async def _claims(
    ctx: _Ctx,
    claims: ListingClaims | None,
    pairs: list[ViewPair],
    usable: list[str] | None = None,
) -> tuple[list[ClaimsFinding], bool, str | None]:
    """(findings, claims_available, caveat)."""
    if claims is None:
        return [], False, NO_CLAIMS_CAVEAT
    if not pairs:
        return [], False, None
    try:
        budget = max(0.0, ctx.remaining_s() - ctx.deps.settings.advise_cap_s)  # leave advise time
        found = await asyncio.wait_for(
            check_claims(ctx.deps.jev, claims, pairs, ctx.deps.settings, usable), budget
        )
        few = usable is not None and len(usable) < MIN_USABLE_VIEWS
        return found, True, FEW_VIEWS_CAVEAT if few else None
    except Exception as exc:  # noqa: BLE001 claims are optional; never fail the comparison
        log.warning("claims stage failed: %s", safe_exc(exc))
        return [], False, CLAIMS_FAILED_CAVEAT


async def _verdict(ctx: _Ctx, resolved: sources.Resolved) -> tuple[Verdict, list[JevViewScores]]:
    if resolved.quality_issues:
        return _quality_verdict(resolved.quality_issues), []
    start = ctx.deps.clock()
    scores, failures = await _judge(ctx, resolved.pairs)
    ctx.lap("judge", start)
    verdict = aggregate(
        scores, failures, len(resolved.pairs), resolved.alignment, resolved.alignment_mode
    )
    return verdict, scores


def _rejected(ctx: _Ctx) -> CompareResponse:
    """Teammate's match gate said `mismatch`: no resolve, no Jev, no claims (R8 escalate)."""
    verdict = _quality_verdict(()).model_copy(
        update={"cause": "listing_rejected", "reason": REJECTED_REASON, "caveats": []}
    )
    rplan = plan(verdict, [], ctx.req.attempt)
    step = template_step(rplan)
    ctx.lap("total", ctx.t0)
    return CompareResponse(
        comparison_id=ctx.req.comparison_id, status="done", verdict=verdict,
        claims_available=False, claims_findings=[], next_step=step,
        explanation=build_explanation(rplan, verdict, [], step), error=None,
        model_ids={}, timings_ms=ctx.timings, run_id=str(ctx.req.comparison_id),
    )  # fmt: skip


async def _compare(ctx: _Ctx) -> CompareResponse:
    req, deps = ctx.req, ctx.deps
    _quiet("request", ctx.run.save_json, "request.json", req)
    if req.listing_match_check is not None and req.listing_match_check.verdict == "mismatch":
        return _rejected(ctx)
    start = deps.clock()
    resolved = await asyncio.to_thread(
        _gated_resolve, deps.resolver, req, deps.settings, deps.renderer
    )
    ctx.lap("resolve", start)
    check_request_bytes([b for p in resolved.pairs for b in (p.png_a, p.png_b)])
    _save_pairs(ctx.run, resolved.pairs)
    pre, scores = await _verdict(ctx, resolved)

    start = deps.clock()
    claims = resolve_claims(req.claims, deps.claims_provider, req.listing_id)
    findings, available, claims_caveat = await _claims(
        ctx, claims, resolved.pairs, usable_labels(scores)
    )
    ctx.lap("claims", start)

    next_plan = plan(pre, findings, req.attempt)  # PRE-claims verdict (AM-08)
    reported = apply_claims(pre, findings)
    extra = [c for c in (claims_caveat,) if c]
    if req.view_pairs is None and not deps.settings.renderer_validated:
        extra.append(UNVALIDATED_CAVEAT)
    reported = reported.model_copy(update={"caveats": [*reported.caveats, *extra]})

    start = deps.clock()
    groq = _RecordingGroq(deps.groq)
    advise_cap = min(deps.settings.advise_cap_s, ctx.remaining_s())
    st = dataclasses.replace(deps.settings, advise_cap_s=advise_cap)
    step = await draft(groq, next_plan, reported, findings, claims, st)
    _quiet("groq", ctx.run.save_json, "groq.json", {"calls": groq.records})
    ctx.lap("advise", start)
    ctx.lap("total", ctx.t0)
    return CompareResponse(
        comparison_id=req.comparison_id, status="done", verdict=reported,
        claims_available=available, claims_findings=findings, next_step=step,
        explanation=build_explanation(next_plan, reported, findings, step), error=None,
        model_ids={
            "jev": scores[0].model if scores else deps.settings.jev_model,
            "groq": step.drafted_by,
        },
        timings_ms=ctx.timings, run_id=str(req.comparison_id),
    )  # fmt: skip


async def compare(req: CompareRequest, deps: Deps) -> CompareResponse:
    ctx = _Ctx(req, deps, deps.runlog_factory(str(req.comparison_id)), deps.clock())
    try:
        response = await asyncio.wait_for(_compare(ctx), deps.settings.request_cap_s)
    except AgentError as err:
        log.warning("compare failed: %s %s", err.code.value, safe_exc(err))
        response = _failed(ctx, err.code)
    except TimeoutError:
        response = _failed(ctx, ErrorCode.INTERNAL)
    except Exception as exc:  # noqa: BLE001 last line of defence; detail goes to the log only
        log.error("compare crashed: %s", safe_exc(exc))
        response = _failed(ctx, ErrorCode.INTERNAL)
    _quiet(
        "response", ctx.run.save_json, "response.json", response
    )  # failed responses are never persisted
    return response
