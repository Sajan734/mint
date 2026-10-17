"""Listing claims vs buyer views (U19). Claims never change the verdict label (AM-08/09/10)."""

import asyncio
import json
import logging
import re
import secrets
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError
from typesafe_sdk import Image

from buyer_agent.config import Settings
from buyer_agent.images import normalise_png
from buyer_agent.jev_client import JevClient
from buyer_agent.jev_prompts import CLAIM_VIEW_KEYS, claim_label, claim_question
from buyer_agent.listing_adapter import parse_claims
from buyer_agent.models import ClaimsFinding, ListingClaims, Verdict, ViewPair

log = logging.getLogger(__name__)
SUPPORTED_MIN = 0.7
CONTRADICTED_MAX = 0.3
MAX_CLAIMS = 8
SAME_PENALTY = 0.8
TARGET_AZIMUTHS = (0.0, 90.0, 180.0, 270.0)
FINE_MARK_WORDS = (
    "no marks", "no scratch", "no scuff", "no dent", "no damage", "no wear", "no flaw",
    "unmarked", "scratch-free", "scratch free", "flawless", "pristine", "like new",
    "perfect condition", "mint condition", "without marks", "without scratches",
)  # fmt: skip
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ClaimsProvider(Protocol):
    def get(self, listing_id: str) -> ListingClaims | None: ...


class FileClaimsProvider:
    """`{directory}/{listing_id}.json`. Missing or invalid file -> None plus a warning."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)

    def get(self, listing_id: str) -> ListingClaims | None:
        path = self._dir / f"{listing_id}.json"
        if not _ID_RE.fullmatch(listing_id) or not path.is_file():
            log.warning("no claims file for listing")
            return None
        try:
            return parse_claims(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError):
            log.warning("invalid claims file for listing")
            return None


def resolve_claims(
    request_claims: ListingClaims | None, provider: ClaimsProvider | None, listing_id: str
) -> ListingClaims | None:
    """request.claims takes priority over the provider."""
    if request_claims is not None:
        return request_claims
    return provider.get(listing_id) if provider is not None else None


def pick_claim_views(pairs: list[ViewPair]) -> list[ViewPair]:
    """4 buyer views: nearest azimuth to 0/90/180/270, else indices 0, n//4, n//2, 3n//4."""
    n = len(pairs)
    if n and all(p.azimuth_deg is not None for p in pairs):
        free, chosen = list(range(n)), []
        for target in TARGET_AZIMUTHS:
            if not free:
                break
            best = min(free, key=lambda i: _angle_gap(pairs[i].azimuth_deg or 0.0, target))
            free.remove(best)
            chosen.append(best)
        return [pairs[i] for i in chosen]
    return [pairs[i] for i in dict.fromkeys((0, n // 4, n // 2, 3 * n // 4)) if i < n]


def _angle_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _is_fine_mark(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in FINE_MARK_WORDS)


def _finding(claim: str, source: str, status: str, p: float | None = None, views=()):
    return ClaimsFinding(
        claim=claim[:200], source=source, status=status, p_present=p, views=list(views)
    )


def _status(p: float) -> str:
    if p >= SUPPORTED_MIN:
        return "supported"
    return "contradicted" if p <= CONTRADICTED_MAX else "unverifiable"


async def _check_one(
    client: JevClient,
    text: str,
    source: str,
    state: dict,
    labels: list[str],
    sem: asyncio.Semaphore,
    settings: Settings,
    key: str,
) -> ClaimsFinding:
    label = claim_label(text)
    if label is None:  # AM-10: never send non-allowlisted text
        return _finding(text, source, "unverifiable")
    question = {"claim": claim_question(label, secrets.token_hex(8))}
    try:
        async with sem:
            answer = await asyncio.wait_for(
                client.ask(state, question, key=key), settings.jev_wait_for_s
            )
        p = float(answer.nouls["claim"])
        status = _status(p)
    except Exception as exc:  # noqa: BLE001 any claim-check failure is unverifiable, never an error
        log.warning("claim check failed: %s", type(exc).__name__)
        return _finding(text, source, "unverifiable")
    return _finding(text, source, status, p, labels if status != "unverifiable" else [])


async def check_claims(
    client: JevClient, claims: ListingClaims, pairs: list[ViewPair], settings: Settings
) -> list[ClaimsFinding]:
    items = [(t, "accessory") for t in claims.accessories_included]
    items += [(t, "condition_note") for t in claims.condition_notes]
    items = items[:MAX_CLAIMS]
    views = pick_claim_views(pairs)
    state: dict = {}
    labels: list[str] = []
    for pair, k in zip(views, CLAIM_VIEW_KEYS, strict=False):
        try:
            state[k] = Image(normalise_png(pair.png_b, settings.claims_max_side))
            labels.append(pair.label)
        except Exception as exc:  # noqa: BLE001 unusable view is skipped
            log.warning("claim view skipped: %s", type(exc).__name__)
    sem = asyncio.Semaphore(settings.concurrency)
    jobs = []
    for i, (text, source) in enumerate(items):
        if _is_fine_mark(text) or not state:
            jobs.append(_unverifiable(text, source))
        else:
            jobs.append(
                _check_one(client, text, source, state, labels, sem, settings, f"claim-{i}")
            )
    findings = list(await asyncio.gather(*jobs))
    if claims.condition_grade is not None and claims.condition_grade >= 9:
        findings.append(
            _finding(
                f"condition grade {claims.condition_grade:g}", "condition_grade", "unverifiable"
            )
        )
    return findings


async def _unverifiable(text: str, source: str) -> ClaimsFinding:
    return _finding(text, source, "unverifiable")


def apply_claims(verdict: Verdict, findings: list[ClaimsFinding]) -> Verdict:
    """Only `same` + a contradicted finding lowers the score (x0.8). Label never changes."""
    if (
        verdict.label == "same"
        and verdict.evidence_score is not None
        and any(f.status == "contradicted" for f in findings)
    ):
        return verdict.model_copy(
            update={"evidence_score": round(verdict.evidence_score * SAME_PENALTY, 6)}
        )
    return verdict
