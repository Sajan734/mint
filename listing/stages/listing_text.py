"""listing_text: Identity -> ListingDraft (Gemini, factual, no price or condition).

Fixture items that have stubs/listing_text.json stay offline. Anything else calls Gemini.
When identify backed an exact model, one Serper web search for it first collects sources about that model (titles
and snippets from its pages); the text may then state the model's features, but only ones the sources state. Without
an exact model there are no sources and no specs: nothing says which product's specs they would be.
Gemini writes the title, description and tags; attributes are built in code from the Identity, so every one
is backed. Code checks the text (title length, price or condition words, and specs or model numbers that neither the
Identity nor the sources back). On a problem Gemini gets one retry with the problems listed; if it still fails, or
Gemini is unreachable, a plain draft is built from the Identity in code. A missing GEMINI_API_KEY still raises.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import timing
from contracts import Identity, ListingDraft, RunContext, backed_by_text
from gemini import contract_schema, generate_json
from stages._fixture import has_stub, load_stub
from stages.identify import MissingKeyError

TEXT = {
    "title_limit_chars": 80,  # titles must be shorter than this
    "max_tags": 8,
    "max_attempts": 2,  # first answer + one retry with the problems listed
    # A slow Gemini can't hold up the listing: each call gets timeout_s (seen: 1.0-2.3 s), the whole draft budget_s,
    # then the template is used, as on any other Gemini failure.
    "timeout_s": 15.0,
    "budget_s": 25.0,
    # Sources about an exact model: one Serper web search, its top results' titles and snippets.
    "sources_endpoint": "https://google.serper.dev/search",
    "sources_country": "ca",
    "max_sources": 6,
    "sources_timeout_s": 8.0,
    "min_mask_chars": 2,  # Identity values shorter than this (e.g. "L", "+") are not masked out
}

DRAFT_FIELDS = ["title", "description", "tags"]
TEMPLATE_FALLBACK_SUBJECT = "Item"

# Matched as whole words or phrases, case-insensitively, after Identity values are masked out.
PRICE_WORDS = (
    "price", "priced", "cheap", "bargain", "deal", "offer", "obo", "msrp", "retail", "worth", "value",
    "discount", "cad", "usd", "dollars",
)
CONDITION_WORDS = (
    "condition", "mint", "pristine", "flawless", "excellent", "perfect", "used", "unused", "refurbished",
    "brand new", "like new", "new in box", "barely", "gently", "lightly", "scratch", "scratches", "scratched",
    "scuff", "scuffs", "scuffed", "dent", "dented", "crack", "cracked", "stain", "stained", "damage", "damaged",
    "broken", "signs of wear", "wear and tear", "light wear", "heavy wear", "normal wear",
)
SPEC_PHRASES = ("battery life", "hours of", "noise cancel", "noise-cancel", "industry-leading", "bluetooth 5")
CURRENCY_CHARS = "$€£¥"
SPEC_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?[\s-]?(?:h|hrs?|hours?|mah|mm|cm|in|inch(?:es)?|w|watts?|hz|khz|mhz|ghz|db|gb|tb|mb|"
    r"mp|g|kg|lbs?|oz|v|ms|dpi|fps|%)(?![a-z0-9])",
    re.IGNORECASE,
)
CODE_PATTERN = re.compile(r"\b(?=[\w-]*\d)(?=[\w-]*[a-z])[a-z0-9]+(?:-[a-z0-9]+)*\b", re.IGNORECASE)

SYSTEM_PROMPT = """\
You write the text of a second-hand marketplace listing from a product identification (JSON) and, when given, \
sources about that exact product.

Rules:
- Factual, plain tone. No hype, no exclamation marks, no marketing phrases.
- title: shorter than 80 characters, written the way a real listing names the product: brand and model first when \
known, then the product type, then one or two key features from the sources if given, then colour if known.
- description: 2 to 4 short sentences saying what the item is and, when sources are given, its main features as \
the sources state them. Use only facts from the identification and the sources.
- tags: 3 to 8 short lowercase search tags (product type, brand, model, colour, form factor).
- Name a brand only if the identification's brand is not null, and a model only if its model is not null. \
Never name any other brand, model, model number, generation or year, even if you recognise the product.
- Specifications and features (battery life, sizes, weights, connectivity, sensors and the like) only when the \
sources state them for this product; with no sources, none at all.
- Never mention price, value, deals, or condition (new, used, wear, scratches, damage). Another part of the \
listing covers those.\
"""


def response_schema() -> dict[str, Any]:
    return contract_schema(ListingDraft, DRAFT_FIELDS)


def identity_prompt(identity: Identity, sources: list[str] = ()) -> str:
    facts = identity.model_dump(include={"category", "brand", "model", "attributes"})
    text = f"Product identification:\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n"
    if sources:
        text += "\nSources about this exact product:\n" + "\n".join(f"- {s}" for s in sources) + "\n"
    return text + "\nWrite the listing text."


def retry_prompt(identity: Identity, previous: dict[str, Any], problems: list[str], sources: list[str] = ()) -> str:
    return (
        f"{identity_prompt(identity, sources)}\n\nYour previous answer was:\n{json.dumps(previous, ensure_ascii=False)}\n"
        f"It broke these rules:\n" + "\n".join(f"- {p}" for p in problems) + "\nWrite it again, fixing every one."
    )


# --- decisions (pure) -------------------------------------------------------------------------


def identity_attributes(identity: Identity) -> dict[str, str]:
    attributes: dict[str, str] = {}
    if identity.brand:
        attributes["brand"] = identity.brand
    if identity.model:
        attributes["model"] = identity.model
    if identity.category:
        attributes["type"] = identity.category
    for key, value in identity.attributes.items():
        attributes.setdefault(key, value)
    return attributes


def backing_values(identity: Identity) -> list[str]:
    values = [identity.category, identity.brand, identity.model, *identity.visible_text, *identity.attributes.values()]
    return [v for v in values if v]


def _mask(text: str, values: list[str]) -> str:
    """Removes Identity values from the text so a product name can't trip the word checks."""
    for value in sorted(values, key=len, reverse=True):
        if sum(ch.isalnum() for ch in value) < TEXT["min_mask_chars"]:
            continue
        text = re.sub(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", " ", text, flags=re.IGNORECASE)
    return text


def _words_found(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text, re.IGNORECASE)]


def violations(draft: ListingDraft, identity: Identity, sources: list[str] = ()) -> list[str]:
    """Rule problems in the draft. Specs, spec phrases and model numbers are fine when the sources state them."""
    problems = []
    if len(draft.title) >= TEXT["title_limit_chars"]:
        problems.append(f"title is {len(draft.title)} characters; it must be under {TEXT['title_limit_chars']}")
    if not draft.title.strip() or not draft.description.strip():
        problems.append("title and description must not be empty")

    backing = backing_values(identity)
    text = _mask(" \n".join([draft.title, draft.description, *draft.tags]), backing)
    if any(ch in text for ch in CURRENCY_CHARS) or _words_found(text, PRICE_WORDS):
        problems.append(f"mentions price or value: {', '.join(_words_found(text, PRICE_WORDS)) or 'currency symbol'}")
    if found := _words_found(text, CONDITION_WORDS):
        problems.append(f"mentions condition: {', '.join(found)}")
    specs = [m.group(0) for m in SPEC_PATTERN.finditer(text)] + _words_found(text, SPEC_PHRASES)
    specs = [spec for spec in specs if not backed_by_text(spec, list(sources))]
    if specs:
        problems.append(f"states specifications or features no source gives: {', '.join(specs)}")
    codes = [m.group(0) for m in CODE_PATTERN.finditer(text)
             if not backed_by_text(m.group(0), backing + list(sources))]
    codes = [c for c in codes if not SPEC_PATTERN.fullmatch(c)]  # already reported as specs
    if codes:
        problems.append(f"names a model number the identification doesn't have: {', '.join(dict.fromkeys(codes))}")
    return problems


def _squash(text: Any) -> str:
    return " ".join(str(text).split()) if text is not None else ""


def to_draft(raw: dict[str, Any], identity: Identity) -> ListingDraft:
    tags = [_squash(t).lower() for t in raw.get("tags") or [] if _squash(t)]
    return ListingDraft(
        title=_squash(raw.get("title")),
        description=_squash(raw.get("description")),
        attributes=identity_attributes(identity),
        tags=list(dict.fromkeys(tags))[: TEXT["max_tags"]],
    )


def _fit_title(text: str) -> str:
    limit = TEXT["title_limit_chars"] - 1
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0]


def template_draft(identity: Identity) -> ListingDraft:
    """A plain draft built only from the Identity, used when Gemini's text can't be used."""
    name = " ".join(part for part in (identity.brand, identity.model) if part)
    subject = f"{name} {identity.category}".strip() or TEMPLATE_FALLBACK_SUBJECT
    subject = subject[:1].upper() + subject[1:]
    colour = identity.attributes.get("colour") or identity.attributes.get("color")
    title = _fit_title(f"{subject} ({colour})" if colour else subject)
    if len(title) < len(subject):  # the colour didn't fit
        title = _fit_title(subject)
    description = f"{subject}{f' in {colour}' if colour else ''}."
    tags = [t.lower() for t in (identity.category, identity.brand, colour) if t]
    return ListingDraft(
        title=title,
        description=description,
        attributes=identity_attributes(identity),
        tags=list(dict.fromkeys(tags))[: TEXT["max_tags"]],
    )


# --- I/O --------------------------------------------------------------------------------------


def parse_sources(payload: dict[str, Any]) -> list[str]:
    """Titles and snippets of the top web results (and the knowledge panel, if any), as one line each."""
    lines = []
    panel = payload.get("knowledgeGraph") or {}
    if panel.get("description"):
        lines.append(f"{panel.get('title') or ''}: {panel['description']}".strip(": "))
    for key, value in (panel.get("attributes") or {}).items():
        lines.append(f"{key}: {value}")
    for item in payload.get("organic") or []:
        text = " ".join(f"{item.get('title') or ''}. {item.get('snippet') or ''}".split()).strip(". ")
        if text:
            lines.append(text)
    return lines[: TEXT["max_sources"]]


async def fetch_sources(identity: Identity) -> tuple[list[str], dict[str, Any]]:
    """Sources about the exact model, or none (no model, no key, a failed or slow search). Never raises."""
    import httpx

    from stages.baseline_lookup import SEARCH, _require_key

    if identity.specificity != "model":
        return [], {"skipped": "no exact model, so no specs"}
    log: dict[str, Any] = {"query": identity.search_query}
    try:
        with timing.span("serper"):
            async with httpx.AsyncClient(timeout=TEXT["sources_timeout_s"]) as client:
                resp = await client.post(
                    TEXT["sources_endpoint"], json={"q": identity.search_query, "gl": TEXT["sources_country"]},
                    headers={"X-API-KEY": _require_key("SERPER_API_KEY"), "Content-Type": "application/json",
                             "User-Agent": SEARCH["user_agent"]})
        resp.raise_for_status()
        sources = parse_sources(resp.json())
    except (httpx.HTTPError, MissingKeyError, ValueError) as e:
        log["error"] = f"{type(e).__name__}: {e}"
        return [], log
    log["sources"] = sources
    return sources, log


async def write_draft(identity: Identity) -> tuple[ListingDraft, dict[str, Any]]:
    """Gemini with one retry on rule problems, else the template. Returns the draft and a log."""
    sources, log_sources = await fetch_sources(identity)
    log: dict[str, Any] = {"sources": log_sources, "attempts": []}
    contents = identity_prompt(identity, sources)
    for _ in range(TEXT["max_attempts"]):
        try:
            reply = await generate_json(contents, SYSTEM_PROMPT, response_schema(), timeout_s=TEXT["timeout_s"])
        except MissingKeyError:
            raise
        except Exception as e:  # noqa: BLE001  API errors, timeouts, bad JSON: fall back to the template
            log["attempts"].append({"error": f"{type(e).__name__}: {e}"})
            break
        draft = to_draft(reply.raw, identity)
        problems = violations(draft, identity, sources)
        log["attempts"].append(
            {"model": reply.model, "latency_ms": round(reply.latency_ms), "raw": reply.raw, "problems": problems}
        )
        if not problems:
            log["source"] = "gemini"
            return draft, log
        contents = retry_prompt(identity, reply.raw, problems, sources)
    log["source"] = "template"
    return template_draft(identity), log


async def listing_text(ctx: RunContext, identity: Identity) -> ListingDraft:
    if has_stub(ctx, "listing_text"):
        return load_stub(ctx, "listing_text", ListingDraft)
    try:
        draft, log = await asyncio.wait_for(write_draft(identity), TEXT["budget_s"])
    except asyncio.TimeoutError:
        draft, log = template_draft(identity), {"error": f"no draft within {TEXT['budget_s']:.0f} s",
                                                "source": "template"}
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    (ctx.run_dir / "listing_text_raw.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    return draft
