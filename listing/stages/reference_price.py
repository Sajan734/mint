"""reference_price: Identity (+ seller-typed name) -> ReferencePrice, an approximate new price in CAD.

Fixture items that have stubs/reference_price.json stay offline. Anything else runs this chain and never fails:
  1. search-grounded Gemini answer (counts only if Google Search returned sources) -> basis "new_retail"
  2. ungrounded Gemini estimate                                                     -> basis "llm_estimate"
  3. per-category default from CATEGORY_DEFAULTS                                    -> basis "llm_estimate"
Any error or implausible amount falls through to the next source. The source used opens the note and is
recorded with every attempt in runs/<item>/reference_price_raw.json. The seller-typed name, when present,
is the product looked up, since it is more specific than the Identity.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass
from typing import Any

from contracts import Identity, ReferencePrice, RunContext
from gemini import contract_schema, generate_json
from stages._fixture import has_stub, load_stub
from stages.baseline_lookup import baseline_query

PRICE_LOOKUP = {
    "min_cad": 5.0,  # anything outside the absolute range is implausible
    "max_cad": 20000.0,
    "min_ratio_to_default": 0.1,  # when the category matched, the amount must sit within these ratios of its default
    "max_ratio_to_default": 15.0,
    "max_sources_in_note": 2,
}

# (keywords, label, approximate new price in CAD). Keywords match the start of a word in Identity.category;
# the first matching row wins, so more specific rows come first. Rough figures, only a last resort.
CATEGORY_DEFAULTS: tuple[tuple[tuple[str, ...], str, float], ...] = (
    (("earbud", "in-ear", "earphone"), "earbuds", 100.0),
    (("headphone", "headset", "on-ear", "over-ear"), "headphones", 150.0),
    (("mouse", "mice"), "computer mouse", 40.0),
    (("keyboard",), "keyboard", 80.0),
    (("speaker", "soundbar"), "speaker", 120.0),
    (("smartwatch", "watch"), "watch", 300.0),
    (("smartphone", "phone"), "phone", 800.0),
    (("laptop", "notebook computer"), "laptop", 1200.0),
    (("tablet", "e-reader"), "tablet", 500.0),
    (("monitor",), "monitor", 300.0),
    (("camera", "lens"), "camera", 700.0),
    (("controller", "gamepad"), "game controller", 80.0),
    (("console",), "game console", 500.0),
    (("sneaker", "shoe", "boot"), "shoes", 120.0),
    (("backpack", "handbag", "purse", "bag"), "bag", 80.0),
    (("jacket", "coat"), "jacket", 150.0),
    (("book",), "book", 25.0),
    (("toy", "lego"), "toy", 40.0),
    (("blender", "toaster", "kettle", "coffee", "kitchen"), "kitchen appliance", 100.0),
    (("lamp",), "lamp", 50.0),
)
GENERIC_DEFAULT: tuple[str, float] = ("item", 50.0)
CATEGORY_DEFAULT_NOTE = "Category default for {label}; no price lookup succeeded."  # deal_rating checks for this

ANSWER_FIELDS = ["amount_cad", "note"]

SYSTEM_PROMPT = """\
You give the approximate price of a product when bought new in Canada, in Canadian dollars.

- Use the regular new price from the manufacturer or a major Canadian retailer, not a sale, used or \
refurbished price.
- If you only know a US price, convert it to CAD. If the product is discontinued, use its last regular new price.
- If the description names a kind of product rather than one model, give a typical new price for that kind of \
product from that brand, and do not name any specific model in the note.
- If you cannot give a price at all, set amount_cad to 0.
- note: one short sentence saying which product the price is for and where it comes from.\
"""
GROUNDED_INSTRUCTION = "Search the web for the current price before answering."
UNGROUNDED_INSTRUCTION = "Answer from what you know. Do not claim to have looked anything up."


@dataclass(frozen=True)
class Source:
    name: str  # recorded in the raw log
    basis: str
    note_prefix: str
    grounded: bool


GROUNDED = Source("search_grounded", "new_retail", "Search-grounded new price", True)
UNGROUNDED = Source("model_estimate", "llm_estimate", "Model estimate, not looked up", False)


def response_schema() -> dict[str, Any]:
    schema = contract_schema(ReferencePrice, ANSWER_FIELDS)
    schema["properties"]["amount_cad"].pop("exclusiveMinimum", None)  # 0 means "don't know"; code rejects it
    return schema


def price_prompt(identity: Identity, query: str, seller_typed: bool, grounded: bool) -> str:
    lines = [f"The seller says the product is: {query}" if seller_typed else f"Product: {query}"]
    known = ", ".join(f"{k}: {v}" for k, v in (("category", identity.category), ("brand", identity.brand),
                                                ("model", identity.model)) if v)
    if known:
        lines.append(f"Identified from photos as {known}.")
    lines.append(GROUNDED_INSTRUCTION if grounded else UNGROUNDED_INSTRUCTION)
    return "\n".join(lines)


# --- decisions (pure) -------------------------------------------------------------------------


def category_default(category: str) -> tuple[str, float, bool]:
    """Returns (label, amount, matched). matched is False when the generic default was used."""
    for keywords, label, amount in CATEGORY_DEFAULTS:
        if any(re.search(rf"(?<![a-z0-9]){re.escape(k)}", category, re.IGNORECASE) for k in keywords):
            return label, amount, True
    return GENERIC_DEFAULT[0], GENERIC_DEFAULT[1], False


def plausible(amount: Any, category: str) -> str | None:
    """None if the amount is a believable new price for the category, else the reason it isn't."""
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
        return f"amount {amount!r} is not a number"
    if not PRICE_LOOKUP["min_cad"] <= amount <= PRICE_LOOKUP["max_cad"]:
        return f"${amount:,.2f} is outside ${PRICE_LOOKUP['min_cad']:,.0f}-${PRICE_LOOKUP['max_cad']:,.0f}"
    label, default, matched = category_default(category)
    if matched:
        low, high = default * PRICE_LOOKUP["min_ratio_to_default"], default * PRICE_LOOKUP["max_ratio_to_default"]
        if not low <= amount <= high:
            return f"${amount:,.2f} is outside ${low:,.0f}-${high:,.0f} for {label}"
    return None


def source_names(grounding: list[dict[str, Any]]) -> list[str]:
    names = [g.get("title") or g.get("domain") or g.get("uri") for g in grounding]
    return list(dict.fromkeys(n for n in names if n))[: PRICE_LOOKUP["max_sources_in_note"]]


def answer_to_price(source: Source, raw: dict[str, Any], grounding: list[dict[str, Any]], category: str) -> tuple[ReferencePrice | None, str | None]:
    """Returns (price, None) or (None, why the answer was rejected)."""
    if source.grounded and not grounding:
        return None, "no search sources: the answer was not grounded"
    amount = raw.get("amount_cad")
    if problem := plausible(amount, category):
        return None, problem
    note = " ".join(str(raw.get("note") or "").split())
    parts = [f"{source.note_prefix}: {note}" if note else f"{source.note_prefix}."]
    if source.grounded:
        parts.append(f"Sources: {', '.join(source_names(grounding))}.")
    return ReferencePrice(amount_cad=round(float(amount), 2), basis=source.basis, note=" ".join(parts)), None


def default_price(category: str) -> ReferencePrice:
    label, amount, _matched = category_default(category)
    return ReferencePrice(amount_cad=amount, basis="llm_estimate", note=CATEGORY_DEFAULT_NOTE.format(label=label))


def is_category_default(reference: ReferencePrice) -> bool:
    """True if the price is the last-resort category default rather than a looked-up or model-estimated price."""
    prefix = CATEGORY_DEFAULT_NOTE.split("{", 1)[0]
    return reference.basis == "llm_estimate" and reference.note.startswith(prefix)


# --- I/O --------------------------------------------------------------------------------------


async def ask(source: Source, identity: Identity, query: str, seller_typed: bool) -> tuple[ReferencePrice | None, dict[str, Any]]:
    attempt: dict[str, Any] = {"source": source.name}
    tools = None
    if source.grounded:
        from google.genai import types

        tools = [types.Tool(google_search=types.GoogleSearch())]
    try:
        reply = await generate_json(
            price_prompt(identity, query, seller_typed, source.grounded), SYSTEM_PROMPT, response_schema(), tools=tools
        )
    except Exception as e:  # noqa: BLE001  this stage never fails: any error moves on to the next source
        attempt["error"] = f"{type(e).__name__}: {e}"
        return None, attempt
    attempt |= {"model": reply.model, "latency_ms": round(reply.latency_ms), "raw": reply.raw, "grounding": reply.grounding}
    price, problem = answer_to_price(source, reply.raw, reply.grounding, identity.category)
    if problem:
        attempt["rejected"] = problem
    return price, attempt


async def look_up(identity: Identity, seller_name: str | None) -> tuple[ReferencePrice, dict[str, Any]]:
    query = baseline_query(identity, seller_name)
    seller_typed = bool(seller_name and seller_name.strip())
    log: dict[str, Any] = {"query": query, "seller_typed": seller_typed, "attempts": []}
    for source in (GROUNDED, UNGROUNDED):
        price, attempt = await ask(source, identity, query, seller_typed)
        log["attempts"].append(attempt)
        if price is not None:
            log["source"] = source.name
            return price, log
    reasons = "; ".join(a.get("error") or a.get("rejected") or "?" for a in log["attempts"])
    print(f"[reference_price] using the category default for {query!r}: {reasons}", file=sys.stderr)
    log["source"] = "category_default"
    return default_price(identity.category), log


async def reference_price(ctx: RunContext, identity: Identity, seller_name: str | None = None) -> ReferencePrice:
    if has_stub(ctx, "reference_price"):
        return load_stub(ctx, "reference_price", ReferencePrice)
    price, log = await look_up(identity, seller_name)
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    (ctx.run_dir / "reference_price_raw.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    return price
