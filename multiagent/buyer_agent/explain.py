"""Buyer-facing explanation. Every fact comes from code; Groq only polishes friendly_summary."""

from collections.abc import Sequence

from buyer_agent.models import ClaimsFinding, Explanation, NextStep, Verdict
from buyer_agent.planner import Plan

STRONG, MODERATE = 0.8, 0.5
DISCLAIMER = (
    "This is an automated visual comparison and can be wrong. It does not check price or payment."
)
DIFF_TEXT = {
    "part_diff": "a part or piece looks different or missing",
    "color_diff": "colours look different",
    "shape_diff": "the overall shape looks different",
    "any_diff": "some other difference was seen",
}
CLAIM_LINE = {
    "supported": "Listing says {c}. We can see it.",
    "contradicted": "Listing says {c}. We could not see it in your scan.",
    "unverifiable": "Listing says {c}. We cannot check this from the scan.",
}
HEADLINE = {
    "none": "The item you received appears to match the listing.",
    "request_refund": "The item you received likely does not match the listing.",
    "message_seller": "The item you received appears to differ from the listing in some way.",
    "request_more_photos": "We could not tell for sure, so more photos are likely needed.",
    "escalate": "This check appears unresolved, so support should likely look at it.",
}
MAX_REFUND_CLAIMS = 3


def _views(verdict: Verdict) -> int:
    ev = verdict.evidence
    return ev.usable_views or ev.answered_views or ev.requested_views


def how_sure(score: float | None) -> str:
    if score is None:
        return "We could not rate how strong the evidence is. This is not proof."
    word = "fairly strong" if score >= STRONG else "moderate" if score >= MODERATE else "weak"
    return f"We have {word} evidence. This is not proof."


def found_lines(verdict: Verdict) -> list[str]:
    total = _views(verdict)
    lines = [
        f"{DIFF_TEXT[cat].capitalize()} (in {len(ev.views)} of {total} views)."
        for cat, ev in verdict.evidence.categories.items()
        if cat in verdict.evidence.flagged and ev.views
    ]
    if lines:
        return lines
    if verdict.label in ("same", "different"):
        return ["We saw no clear difference between the two scans."]
    return ["The scans could not be compared reliably."]


def claim_lines(findings: Sequence[ClaimsFinding]) -> list[str]:
    return [CLAIM_LINE[f.status].format(c=f.claim) for f in findings]


def _headline(verdict: Verdict, plan: Plan) -> str:
    if verdict.label == "listing_rejected":
        return "This listing did not pass the platform's product check."
    return HEADLINE[plan.category]


def _compared(verdict: Verdict) -> str:
    if verdict.label == "listing_rejected":
        return "We did not compare the scans, because the listing failed the product check first."
    return f"We compared {_views(verdict)} views of the listing scan with your scan."


def refund_text(verdict: Verdict, findings: Sequence[ClaimsFinding]) -> str:
    flagged = [DIFF_TEXT[c] for c in verdict.evidence.flagged if c in DIFF_TEXT]
    diffs = "; ".join(flagged) or "the item looks different"
    text = (
        "Hello, I received the item and compared a 3D scan of it with the scan in your listing "
        f"({_views(verdict)} views). The comparison appears to show that {diffs}."
    )
    bad = [f.claim for f in findings if f.status == "contradicted"][:MAX_REFUND_CLAIMS]
    if bad:
        text += " I also could not see in my scan: " + "; ".join(bad) + "."
    return (
        text + " I have attached the comparison photos. Could you please review them and tell me "
        "how you would like to resolve this, for example with a refund or a return? Thank you."
    )


def _steps(verdict: Verdict, plan: Plan, found: list[str]) -> list[str]:
    if verdict.label == "listing_rejected":
        return [
            "Do not rely on this listing's scan.",
            "Contact support and tell them the listing did not pass the product check.",
        ]
    if plan.category == "request_more_photos":
        if plan.audience == "buyer":
            return [
                "Walk fully around the item in good light and scan it again, moving slowly.",
                "Then run the check again.",
            ]
        return [
            "Ask the seller for more photos of the item from all sides.",
            "Keep their reply with your records.",
        ]
    steps = {
        "none": ["Nothing to do. Keep your photos for your records."],
        "message_seller": [
            "Message the seller and describe the differences listed above.",
            "Attach the comparison photos.",
            "Keep a record of the conversation.",
        ],
        "request_refund": [
            "Contact the seller through the marketplace first.",
            "Attach these comparison photos.",
            "State the differences: " + " ".join(found),
            "Keep a record of messages and photos.",
            "If the marketplace has a return window, check it and act inside it.",
        ],
        "escalate": [
            "Contact the marketplace's support team.",
            "Share these results and your comparison photos.",
        ],
    }
    return steps[plan.category]


def build_explanation(
    plan: Plan, verdict: Verdict, findings: Sequence[ClaimsFinding], step: NextStep
) -> Explanation:
    found = found_lines(verdict)
    sure = how_sure(verdict.evidence_score)
    headline = _headline(verdict, plan)
    friendly = step.summary if not step.is_template else f"{headline} {sure}"
    return Explanation(
        headline=headline,
        what_we_compared=_compared(verdict),
        what_we_found=found,
        how_sure=sure,
        listing_vs_item=claim_lines(findings),
        what_to_do=_steps(verdict, plan, found),
        caveats=list(verdict.caveats),
        disclaimer=DISCLAIMER,
        friendly_summary=friendly,
    )
