"""Pure next-step planner (DESIGN 6.4 + AM-08/AM-12). First matching row wins."""

from buyer_agent.models import ActionCategory, ClaimsFinding, Label, Strict, Verdict

REFUND_SCORE = 0.7
ESCALATING = frozenset({"low_quality", "misaligned"})  # causes that escalate on a retry


class Plan(Strict):
    category: ActionCategory
    audience: str
    reason_code: str
    cited_views: list[Label]


def _verdict_views(verdict: Verdict) -> list[Label]:
    seen: dict[str, None] = {}
    for cat in verdict.evidence.categories.values():
        seen.update(dict.fromkeys(cat.views))
    return list(seen)


def plan(verdict: Verdict, findings: list[ClaimsFinding], attempt: int) -> Plan:
    """Pick the next step. Pass the PRE-claims verdict (AM-08).

    The verdict is binary; `cause` marks a `different` that came from a gate, not a measurement.
    R0 escalates a low_quality/misaligned cause from attempt 2 (AM-12). A measured `different`
    still goes to R4/R5 on any attempt.
    """
    label, cause = verdict.label, verdict.cause
    views = _verdict_views(verdict)
    if cause == "listing_rejected":  # R8: the listing itself failed the product match
        return Plan(category="escalate", audience="support", reason_code="R8", cited_views=[])
    if attempt >= 2 and cause in ESCALATING:
        return Plan(category="escalate", audience="support", reason_code="R0", cited_views=views)
    if cause in ESCALATING:
        code = "R1" if cause == "low_quality" else "R2"
        return Plan(
            category="request_more_photos", audience="buyer", reason_code=code, cited_views=[]
        )
    contradicted = [f for f in findings if f.status == "contradicted"]
    if label == "different":
        flagged = set(verdict.evidence.flagged)
        strong = (verdict.evidence_score or 0.0) >= REFUND_SCORE
        physical = bool(flagged & {"part_diff", "shape_diff"})
        if strong and (physical or any(f.source == "accessory" for f in contradicted)):
            return Plan(
                category="request_refund", audience="seller", reason_code="R4", cited_views=views
            )
        return Plan(
            category="message_seller", audience="seller", reason_code="R5", cited_views=views
        )
    if contradicted:
        seen = dict.fromkeys(v for f in contradicted for v in f.views)
        return Plan(
            category="message_seller", audience="seller", reason_code="R6", cited_views=list(seen)
        )
    return Plan(category="none", audience="none", reason_code="R7", cited_views=[])
