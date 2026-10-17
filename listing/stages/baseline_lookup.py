"""baseline_lookup: seller's name or Identity.search_query -> Baseline (one clean product photo).

Order: manual baseline (ctx.manual_baseline; never searches) -> fixture stub -> no search when nothing
names the product (no seller-typed name, and no brand, model or other text read off the item in the query)
-> live search.
Live search: Serper image search -> metadata pre-filter -> download and fit to Jev's limits -> one Jev
photo check per candidate -> choose_candidate() in code. If nothing usable is found the Baseline has
image_path=None, and match_gate treats the match as uncertain.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient, Image, RetryPolicy, TypeSafeError

from contracts import Baseline, Identity, RunContext
from images import FittedImage, ImageProblem, fit_for_jev
from jev_questions import BASELINE_CONTEXT, BASELINE_QUESTIONS, IMAGE_HEADERS, MODEL
from stages._fixture import has_stub, load_stub
from stages.identify import MissingKeyError, text_in_query

LISTING_ROOT = Path(__file__).resolve().parent.parent

SEARCH = {
    "endpoint": "https://google.serper.dev/images",
    "num": 10,
    "query_suffix": " product photo",  # first attempt; the second attempt uses the plain query
    "timeout_s": 15.0,
    "max_candidates": 6,
    "download_timeout_s": 10.0,
    "max_download_bytes": 15 * 1024 * 1024,
    "user_agent": "MintListing/0.1",  # generic; never personal details
    "min_side_px": 280,
    "aspect_min": 0.5,
    "aspect_max": 2.0,
}

JEV = {"timeout_s": 30.0, "max_retries": 1}

THRESHOLDS = {
    "yes_min": 0.70,  # questions where yes is good must reach this
    "no_max": 0.30,  # questions where yes is bad must stay at or below this
}
GOOD_IF_YES = ("single_product", "plain_background", "matches_query")
GOOD_IF_NO = ("people_or_packaging", "overlay_or_collage")

MANUAL_IMAGE_NAMES = ("baseline.jpg", "baseline.jpeg", "baseline.png")
MANUAL_SOURCE_FILE = "baseline.json"


@dataclass
class SearchResult:
    position: int
    image_url: str
    page_url: str | None = None
    domain: str | None = None
    width: int | None = None
    height: int | None = None
    title: str | None = None


@dataclass
class Candidate:
    result: SearchResult
    image: FittedImage | None = None
    answers: dict[str, float] | None = None
    problem: str | None = None

    def log(self) -> dict[str, Any]:
        entry: dict[str, Any] = asdict(self.result)
        if self.image:
            entry["fitted"] = {"width": self.image.width, "height": self.image.height, "notes": self.image.notes}
        if self.answers is not None:
            entry["answers"] = self.answers
            entry["failed"] = failed_criteria(self.answers)
            entry["weakest"] = weakest_criterion(self.answers)
        if self.problem:
            entry["problem"] = self.problem
        return entry


NO_PRODUCT_NOTE = "not searched: no text read off the item and no product name typed by the seller"


def baseline_query(identity: Identity, seller_name: str | None) -> str:
    if seller_name and seller_name.strip():
        return seller_name.strip()
    return identity.search_query


def has_claim(identity: Identity, seller_name: str | None) -> bool:
    """Someone named this exact product: the seller typed its name, or its model is printed on it. Only then can a
    reference photo that looks like a different product mean the scan is the wrong item (see match_gate)."""
    return bool(seller_name and seller_name.strip()) or identity.model is not None


def names_a_product(identity: Identity, seller_name: str | None) -> bool:
    """Worth searching: a product name, or text read off the item in the query (a brand or product line such as
    "ThinkPad"). A query of colour and category alone ("white stuffed animal") finds some other product."""
    if has_claim(identity, seller_name) or identity.brand is not None:
        return True
    return bool(text_in_query(identity.visible_text, identity.search_query))


# --- decisions (pure) -------------------------------------------------------------------------


def failed_criteria(answers: dict[str, float]) -> list[str]:
    failed = [q for q in GOOD_IF_YES if answers.get(q, 0.0) < THRESHOLDS["yes_min"]]
    failed += [q for q in GOOD_IF_NO if answers.get(q, 1.0) > THRESHOLDS["no_max"]]
    return failed


def weakest_criterion(answers: dict[str, float]) -> float:
    """How strongly the photo meets its worst criterion: 1.0 is perfect on every question."""
    goods = [answers.get(q, 0.0) for q in GOOD_IF_YES] + [1.0 - answers.get(q, 1.0) for q in GOOD_IF_NO]
    return min(goods)


def choose_candidate(candidates: list[Candidate]) -> Candidate | None:
    passing = [c for c in candidates if c.answers is not None and not failed_criteria(c.answers)]
    if not passing:
        return None
    return max(passing, key=lambda c: (weakest_criterion(c.answers), -c.result.position))


def parse_results(payload: dict[str, Any]) -> list[SearchResult]:
    results = []
    for i, item in enumerate(payload.get("images") or []):
        url = item.get("imageUrl")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        results.append(
            SearchResult(
                position=int(item.get("position") or i + 1),
                image_url=url,
                page_url=item.get("link"),
                domain=item.get("domain"),
                width=item.get("imageWidth"),
                height=item.get("imageHeight"),
                title=item.get("title"),
            )
        )
    return results


def prefilter(results: list[SearchResult]) -> tuple[list[Candidate], list[Candidate]]:
    """Drops results whose reported size can't make a usable baseline. Returns (kept, dropped)."""
    kept, dropped = [], []
    for r in results:
        problem = None
        if r.width and r.height:
            if min(r.width, r.height) < SEARCH["min_side_px"]:
                problem = f"reported {r.width}x{r.height}: too small"
            elif not SEARCH["aspect_min"] <= r.width / r.height <= SEARCH["aspect_max"]:
                problem = f"reported {r.width}x{r.height}: aspect ratio out of range"
        if problem is None and len(kept) >= SEARCH["max_candidates"]:
            problem = "beyond max_candidates"
        (dropped if problem else kept).append(Candidate(r, problem=problem))
    return kept, dropped


# --- I/O --------------------------------------------------------------------------------------


def _require_key(name: str) -> str:
    load_dotenv(LISTING_ROOT.parent / ".env")  # the repo-wide .env
    key = os.environ.get(name, "").strip()
    if not key:
        raise MissingKeyError(f"{name} is missing: add it to the repo-root .env")
    return key


async def search_images(query: str, api_key: str) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=SEARCH["timeout_s"]) as client:
        resp = await client.post(
            SEARCH["endpoint"],
            headers={"X-API-KEY": api_key, "Content-Type": "application/json", "User-Agent": SEARCH["user_agent"]},
            json={"q": query, "num": SEARCH["num"]},
        )
        resp.raise_for_status()
        return parse_results(resp.json())


async def download(client: httpx.AsyncClient, url: str) -> bytes:
    chunks, size = [], 0
    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > SEARCH["max_download_bytes"]:
                raise ImageProblem("download is over the size cap")
            chunks.append(chunk)
    return b"".join(chunks)


async def fetch_and_fit(client: httpx.AsyncClient, candidate: Candidate) -> None:
    try:
        candidate.image = fit_for_jev(await download(client, candidate.result.image_url))
    except (httpx.HTTPError, ImageProblem) as e:
        candidate.problem = f"{type(e).__name__}: {e}"


async def check_photo(jev: AsyncTypeSafeClient, query: str, candidate: Candidate) -> None:
    try:
        resp = await jev.system_one(
            state={"context": BASELINE_CONTEXT, "query": query, "photo": Image(candidate.image.data)},
            questions=BASELINE_QUESTIONS,
            extra_headers=IMAGE_HEADERS,
        )
        candidate.answers = {q: resp.nouls[q].noul for q in BASELINE_QUESTIONS}
    except TypeSafeError as e:
        candidate.problem = f"Jev: {type(e).__name__}: {e}"


def _relative(path: Path) -> str:
    try:
        return path.relative_to(LISTING_ROOT).as_posix()
    except ValueError:
        return str(path)


async def search_attempt(query_sent: str, query: str, serper_key: str, jev: AsyncTypeSafeClient) -> tuple[Candidate | None, dict]:
    attempt: dict[str, Any] = {"query_sent": query_sent}
    try:
        results = await search_images(query_sent, serper_key)
    except (httpx.HTTPError, ValueError) as e:
        attempt["error"] = f"search failed: {type(e).__name__}: {e}"
        return None, attempt
    kept, dropped = prefilter(results)
    headers = {"User-Agent": SEARCH["user_agent"]}
    async with httpx.AsyncClient(timeout=SEARCH["download_timeout_s"], follow_redirects=True, headers=headers) as client:
        await asyncio.gather(*(fetch_and_fit(client, c) for c in kept))
    ready = [c for c in kept if c.image is not None]
    await asyncio.gather(*(check_photo(jev, query, c) for c in ready))
    chosen = choose_candidate(ready)
    attempt["results"] = len(results)
    attempt["candidates"] = [c.log() for c in kept + dropped]
    return chosen, attempt


async def find_baseline(query: str, run_dir: Path) -> tuple[Baseline, dict]:
    """Live search. Never raises for 'nothing found'; raises MissingKeyError if a key is missing."""
    serper_key = _require_key("SERPER_API_KEY")
    _require_key("TYPESAFE_API_KEY")
    log: dict[str, Any] = {"query": query, "attempts": []}
    chosen: Candidate | None = None
    async with AsyncTypeSafeClient(
        model=MODEL, timeout=JEV["timeout_s"], retry=RetryPolicy(max_retries=JEV["max_retries"])
    ) as jev:
        for query_sent in dict.fromkeys([query + SEARCH["query_suffix"], query]):
            chosen, attempt = await search_attempt(query_sent, query, serper_key, jev)
            log["attempts"].append(attempt)
            if chosen:
                break

    if chosen is None:
        errors = [a["error"] for a in log["attempts"] if "error" in a]
        note = "; ".join(errors) if errors else "no search result passed the clean product photo check"
        print(f"[baseline_lookup] nothing usable for {query!r}: {note}", file=sys.stderr)
        log["chosen"] = None
        return Baseline(query=query, image_path=None, source="image_search", note=note), log

    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"baseline{chosen.image.extension}"
    path.write_bytes(chosen.image.data)
    notes = [f"weakest criterion {weakest_criterion(chosen.answers):.2f}", *chosen.image.notes]
    log["chosen"] = chosen.result.image_url
    return (
        Baseline(
            query=query,
            image_path=_relative(path),
            source_url=chosen.result.page_url or chosen.result.image_url,
            source="image_search",
            note="; ".join(notes),
        ),
        log,
    )


def load_manual(ctx: RunContext, query: str) -> Baseline:
    found = next((ctx.item_dir / n for n in MANUAL_IMAGE_NAMES if (ctx.item_dir / n).is_file()), None)
    if found is None:
        names = ", ".join(MANUAL_IMAGE_NAMES)
        return Baseline(
            query=query, image_path=None, source="manual",
            note=f"manual baseline is on, but {_relative(ctx.item_dir)} has none of: {names}",
        )
    source_file = ctx.item_dir / MANUAL_SOURCE_FILE
    source_url = json.loads(source_file.read_text(encoding="utf-8")).get("source_url") if source_file.is_file() else None
    try:
        fitted = fit_for_jev(found.read_bytes())
    except ImageProblem as e:
        return Baseline(query=query, image_path=None, source="manual", source_url=source_url,
                        note=f"manual baseline {found.name} is unusable: {e}")
    path = found
    if fitted.notes:  # changed to fit Jev's limits: use the fitted copy
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.run_dir / f"baseline_manual{fitted.extension}"
        path.write_bytes(fitted.data)
    return Baseline(
        query=query, image_path=_relative(path), source="manual", source_url=source_url,
        note="; ".join(fitted.notes) or None,
    )


async def baseline_lookup(ctx: RunContext, identity: Identity, seller_name: str | None) -> Baseline:
    query = baseline_query(identity, seller_name)
    if ctx.manual_baseline:
        return load_manual(ctx, query)
    if has_stub(ctx, "baseline_lookup"):
        return load_stub(ctx, "baseline_lookup", Baseline).model_copy(update={"query": query})
    if not names_a_product(identity, seller_name):
        return Baseline(query=query, image_path=None, source="image_search", note=NO_PRODUCT_NOTE)
    baseline, log = await find_baseline(query, ctx.run_dir)
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    (ctx.run_dir / "baseline_candidates.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    return baseline
