"""listing_text: Identity -> ListingDraft (Gemini, factual, no price or condition).

Fixture items that have stubs/listing_text.json stay offline. Anything else calls Gemini.
Gemini writes the title, description and tags; attributes are built in code from the Identity, so every one
is backed. Code checks the text (title length, price or condition words, specs, model numbers the Identity
doesn't back). On a problem Gemini gets one retry with the problems listed; if it still fails, or Gemini is
unreachable, a plain draft is built from the Identity in code. A missing GEMINI_API_KEY still raises.
"""

from __future__ import annotations

import json
import re
from typing import Any

from contracts import Identity, ListingDraft, RunContext, backed_by_text
from gemini import contract_schema, generate_json
from stages._fixture import has_stub, load_stub
from stages.identify import MissingKeyError

TEXT = {
    "title_limit_chars": 80,  # titles must be shorter than this
    "max_tags": 8,
    "max_attempts": 2,  # first answer + one retry with the problems listed
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
You write the text of a second-hand marketplace listing from a product identification (JSON).

Rules:
- Factual, plain tone. No hype, no exclamation marks, no marketing phrases.
- title: shorter than 80 characters. Brand and model first when known, then the product type, then colour if known.
- description: 1 to 3 short sentences saying what the item is, using only facts in the identification.
- tags: 3 to 8 short lowercase search tags (product type, brand, colour, form factor).
- Name a brand only if the identification's brand is not null, and a model only if its model is not null. \
Never name any other brand, model, model number, generation or year, even if you recognise the product.
- No specifications or features that are not in the identification: no battery life, sizes, weights, \
wattage, connectivity versions, noise cancelling or similar claims.
- Never mention price, value, deals, or condition (new, used, wear, scratches, damage). Another part of the \
listing covers those.\
"""


def response_schema() -> dict[str, Any]:
    return contract_schema(ListingDraft, DRAFT_FIELDS)


def identity_prompt(identity: Identity) -> str:
    facts = identity.model_dump(include={"category", "brand", "model", "attributes"})
    return f"Product identification:\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n\nWrite the listing text."


def retry_prompt(identity: Identity, previous: dict[str, Any], problems: list[str]) -> str:
    return (
        f"{identity_prompt(identity)}\n\nYour previous answer was:\n{json.dumps(previous, ensure_ascii=False)}\n"
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


def violations(draft: ListingDraft, identity: Identity) -> list[str]:
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
    if specs:
        problems.append(f"states specifications or features not in the identification: {', '.join(specs)}")
    codes = [m.group(0) for m in CODE_PATTERN.finditer(text) if not backed_by_text(m.group(0), backing)]
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


async def write_draft(identity: Identity) -> tuple[ListingDraft, dict[str, Any]]:
    """Gemini with one retry on rule problems, else the template. Returns the draft and a log."""
    log: dict[str, Any] = {"attempts": []}
    contents = identity_prompt(identity)
    for _ in range(TEXT["max_attempts"]):
        try:
            reply = await generate_json(contents, SYSTEM_PROMPT, response_schema())
        except MissingKeyError:
            raise
        except Exception as e:  # noqa: BLE001  API errors, timeouts, bad JSON: fall back to the template
            log["attempts"].append({"error": f"{type(e).__name__}: {e}"})
            break
        draft = to_draft(reply.raw, identity)
        problems = violations(draft, identity)
        log["attempts"].append(
            {"model": reply.model, "latency_ms": round(reply.latency_ms), "raw": reply.raw, "problems": problems}
        )
        if not problems:
            log["source"] = "gemini"
            return draft, log
        contents = retry_prompt(identity, reply.raw, problems)
    log["source"] = "template"
    return template_draft(identity), log


async def listing_text(ctx: RunContext, identity: Identity) -> ListingDraft:
    if has_stub(ctx, "listing_text"):
        return load_stub(ctx, "listing_text", ListingDraft)
    draft, log = await write_draft(identity)
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    (ctx.run_dir / "listing_text_raw.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    return draft
