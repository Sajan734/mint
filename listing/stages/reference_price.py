"""reference_price: Identity (+ seller-typed name) -> ReferencePrice, the new price in CAD.

Fixture items that have stubs/reference_price.json stay offline. Anything else runs this chain and never fails:
  1. real listings: Serper shopping search (Canada) -> Gemini says which results are this product, sold new
     on its own -> code takes the median of their prices (at least 2 listings from 2 sellers) -> "new_retail",
     with the listings recorded in ReferencePrice.sources
  2. search-grounded Gemini answer (counts only if Google Search returned sources) -> basis "new_retail"
     (only when GEMINI["search_grounding"] is on: our free-tier project can't use Search grounding at all)
  3. ungrounded Gemini estimate                                                     -> basis "llm_estimate"
  4. per-category default from CATEGORY_DEFAULTS                                    -> basis "llm_estimate"
Any error or implausible amount falls through to the next source. The source used opens the note and is
recorded with every attempt in runs/<item>/reference_price_raw.json. The seller-typed name, when present,
is the product looked up, since it is more specific than the Identity.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from pydantic import ValidationError

import timing
from contracts import Identity, PriceResultCheck, PriceSource, ReferencePrice, RunContext
from gemini import contract_schema, generate_json
from stages._fixture import has_stub, load_stub
from stages.baseline_lookup import SEARCH, _require_key, baseline_query, names_a_product
from stages.identify import GEMINI, MissingKeyError, build_search_query, text_in_query

# Real listings from Serper's shopping search. Prices come from the result's own price field, parsed in code;
# Gemini only says which results are this product.
SERPER_PRICE = {
    "endpoint": "https://google.serper.dev/shopping",
    "country": "ca",  # gl=ca: Canadian stores, prices in CAD
    "num": 20,
    "timeout_s": 15.0,
    # Which results count as the product. Flash-lite's same_product is not stable in scale from run to run (seen
    # live: the same 20 results, the ThinkPad Essential listings scored 1.0 in one run and 0.3 in the next), but its
    # order is. So the best-scoring tier counts: within same_product_tier of the best score, a result at
    # same_product_min always reaching the tier, and nothing below same_product_floor (nothing fits).
    "same_product_min": 0.70,
    "same_product_tier": 0.10,
    "same_product_floor": 0.25,
    # From 3 listings, prices more than this factor from the first median are dropped. Two listings can't say
    # which one is off (their median is the midpoint), so they must agree within this factor.
    "outlier_ratio": 1.6,
    "min_listings": 2,  # fewer matching listings (or sellers) -> fall back to the estimate
    "min_sellers": 2,
    "max_sellers_in_note": 3,
    # A slow search or check can't hold up the listing: the whole listings attempt gets budget_s (usually ~5 s), the
    # check timeout_s per Gemini attempt (seen: 2.1-2.4 s); then the estimate is used, as on any other failure.
    "budget_s": 12.0,
    "timeout_s": 15.0,
    "max_sources": 10,  # listings recorded in ReferencePrice.sources (the median uses all of them)
}

PRICE_LOOKUP = {
    "min_cad": 5.0,  # anything outside the absolute range is implausible
    "max_cad": 20000.0,
    "min_ratio_to_default": 0.1,  # when the category matched, the amount must sit within these ratios of its default
    "max_ratio_to_default": 15.0,
    "max_sources_in_note": 2,
    "estimate_timeout_s": 15.0,  # per Gemini attempt for the estimate fallbacks
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
LISTINGS_SOURCE = "serper_shopping"  # the raw log's name for the real-listings source

PICK_SYSTEM_PROMPT = """\
You check shopping search results against an item a seller is listing. For every numbered result, return its \
index and:

- same_product: from 0 to 1, how likely the result is the item's product.
  - If a specific model is known (printed on the item, or named by the seller), the result must be that model \
and variant (size, capacity, connectivity). A different model from the same brand or product line is NOT the \
same product, even if it looks similar.
  - If only a brand or product line is known (for example a seller's name like "Lenovo ThinkPad wireless mouse"), \
a result counts when it fits everything that is known about the item: the brand or product line, the kind of \
product, and its description. A different kind of product, or another brand or product line, does not count.
  - The same model in another colour counts as the same product.
- new_single_unit: true only if the result sells the product itself, new, as one unit. False for used, \
refurbished, renewed or open-box items, bundles or kits with other products, multipacks, and accessories or \
replacement parts for the product.

Judge only from the result's title and seller and the description of the item. Do not guess prices. Return one entry for every result.\
"""


@dataclass
class ShopResult:
    """One Serper shopping result, with its price parsed in code."""

    index: int
    title: str
    seller: str | None
    price_text: str | None
    url: str | None
    price_cad: float | None = None
    problem: str | None = None  # why the result can't count, if it can't
    same_product: float | None = None  # Gemini's check, when it ran
    new_single_unit: bool | None = None


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


FOREIGN_CURRENCY = re.compile(r"US\s*\$|USD|EUR|GBP|€|£|¥", re.IGNORECASE)
CAD_MARKER = re.compile(r"\$|\bCAD\b", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d\s  ,.]*\d|\d")


def parse_cad(text: Any) -> tuple[float | None, str | None]:
    """A shopping result's price string -> (dollars, None) or (None, why not). Results come from Canadian search
    (gl=ca), so "$" is CAD; "CA$", "C$" and "CAD" are too. French style ("1 299,99 $") is understood."""
    if not isinstance(text, str) or not text.strip():
        return None, "no price"
    if FOREIGN_CURRENCY.search(text):
        return None, f"price {text!r} is not in Canadian dollars"
    if not CAD_MARKER.search(text):
        return None, f"price {text!r} has no currency"
    match = NUMBER.search(text)
    if match is None:
        return None, f"no number in price {text!r}"
    digits = re.sub(r"[\s  ]", "", match.group())
    if "," in digits and "." in digits:  # the later one is the decimal mark
        thousands = "," if digits.rfind(",") < digits.rfind(".") else "."
        digits = digits.replace(thousands, "").replace(",", ".")
    elif "," in digits:  # "26,99" is a decimal comma, "1,299" a thousands comma
        head, _, tail = digits.rpartition(",")
        digits = f"{head.replace(',', '')}.{tail}" if len(tail) == 2 else digits.replace(",", "")
    try:
        return float(digits), None
    except ValueError:
        return None, f"can't read price {text!r}"


def seller_key(result: ShopResult) -> str | None:
    return " ".join(result.seller.casefold().split()) if result.seller else None


def combine_listings(matched: list[ShopResult]) -> tuple[float | None, list[ShopResult], str]:
    """Matching listings -> (median price or None, the listings it rests on, what happened). Duplicates (same
    seller and price) count once; prices far from the first median are dropped; then it needs min_listings
    listings from min_sellers named sellers, so one listing can't set the price on its own."""
    unique: dict[tuple[str | None, float], ShopResult] = {}
    for r in matched:
        unique.setdefault((seller_key(r), r.price_cad), r)
    listings = list(unique.values())
    if not listings:
        return None, [], "no result was this product, sold new"
    ratio = SERPER_PRICE["outlier_ratio"]
    if len(listings) == 2:
        low, high = sorted(r.price_cad for r in listings)
        if high > low * ratio:
            return None, listings, f"the 2 matching listings disagree: ${low:,.2f} and ${high:,.2f}"
    first = statistics.median(r.price_cad for r in listings)
    kept = [r for r in listings if first / ratio <= r.price_cad <= first * ratio]
    sellers = {k for r in kept if (k := seller_key(r))}
    if not enough(kept):
        return None, kept, (f"only {len(kept)} matching listing(s) from {len(sellers)} seller(s); need "
                            f"{SERPER_PRICE['min_listings']} from {SERPER_PRICE['min_sellers']}")
    dropped = len(listings) - len(kept)
    return (round(statistics.median(r.price_cad for r in kept), 2), kept,
            f"median of {len(kept)} listing(s)" + (f", {dropped} outlier(s) dropped" if dropped else ""))


def seller_names(kept: list[ShopResult]) -> str:
    names = list(dict.fromkeys(r.seller for r in kept if r.seller))
    cap = SERPER_PRICE["max_sellers_in_note"]
    shown = ", ".join(names[:cap])
    return f"{shown} and {len(names) - cap} more" if len(names) > cap else shown


def listings_price(amount: float, kept: list[ShopResult]) -> ReferencePrice:
    note = f"Median new price of {len(kept)} current listings in Canada ({seller_names(kept)})."
    sources = [PriceSource(title=r.title, seller=r.seller, price_cad=r.price_cad, url=r.url)
               for r in kept[: SERPER_PRICE["max_sources"]]]
    return ReferencePrice(amount_cad=amount, basis="new_retail", note=note, sources=sources)


def parse_results(payload: dict[str, Any], category: str) -> list[ShopResult]:
    """Serper's shopping results, numbered from 0, each with its price parsed and checked for the category."""
    results = []
    for item in (payload.get("shopping") or [])[: SERPER_PRICE["num"]]:
        title = " ".join(str(item.get("title") or "").split())
        if not title:
            continue
        r = ShopResult(index=len(results), title=title, seller=item.get("source") or None,
                       price_text=item.get("price"), url=item.get("link") or None)
        r.price_cad, r.problem = parse_cad(r.price_text)
        if r.problem is None and (problem := plausible(r.price_cad, category)):
            r.price_cad, r.problem = None, problem
        results.append(r)
    return results


def same_product_cut(scores: list[float]) -> float:
    """The same_product a result needs, from the scores of the priced, new, single-unit results: the best tier."""
    best = max(scores, default=0.0)
    t = SERPER_PRICE
    return max(t["same_product_floor"], min(t["same_product_min"], best - t["same_product_tier"]))


def enough(listings: list[ShopResult]) -> bool:
    """Enough listings to price from: min_listings of them, from min_sellers named sellers."""
    return (len(listings) >= SERPER_PRICE["min_listings"]
            and len({k for r in listings if (k := seller_key(r))}) >= SERPER_PRICE["min_sellers"])


def apply_checks(results: list[ShopResult], raw: dict[str, Any], widen: bool = False) -> list[ShopResult]:
    """Records Gemini's check on each result and returns the ones that count: priced, sold new on their own, and in
    the best same_product tier (same_product_cut). A result Gemini skipped doesn't count.
    widen (no model is printed on the item): while the tiers taken are too thin to price from, the next tier down is
    added, down to same_product_floor. Gemini can pick out one sibling model of the line at 1.0 and score the rest
    of the line 0.5 (seen live on two ThinkPad mouse scans), and one listing can't set a price."""
    checks: dict[int, PriceResultCheck] = {}
    for entry in raw.get("results") or []:
        try:
            check = PriceResultCheck.model_validate(entry)
        except ValidationError:
            continue
        checks.setdefault(check.index, check)
    for r in results:
        check = checks.get(r.index)
        if check is None:
            r.problem = r.problem or "not checked"
            continue
        r.same_product, r.new_single_unit = check.same_product, check.new_single_unit
        if r.problem is None and not check.new_single_unit:
            r.problem = "not sold new on its own"
    candidates = [r for r in results if r.problem is None]
    cut = same_product_cut([r.same_product for r in candidates])
    if widen:
        floor = SERPER_PRICE["same_product_floor"]
        lower = sorted({r.same_product for r in candidates if floor <= r.same_product < cut}, reverse=True)
        while lower and not enough([r for r in candidates if r.same_product >= cut]):
            cut = lower.pop(0)
    matched = []
    for r in candidates:
        if r.same_product < cut:
            r.problem = f"not this product (same_product {r.same_product:.2f}, needs {cut:.2f})"
        else:
            matched.append(r)
    return matched


def pick_schema() -> dict[str, Any]:
    item = contract_schema(PriceResultCheck, ["index", "same_product", "new_single_unit"])
    return {"type": "object", "properties": {"results": {"type": "array", "items": item}}, "required": ["results"]}


def price_query(identity: Identity, seller_name: str | None) -> str:
    """What to search the shops for: the seller's name for the product, else the text read off the item, its model
    and its kind. No colour: it doesn't change the price, and identify words it differently from run to run ("black",
    "black and red"), which changed the results and so the price."""
    if seller_name and seller_name.strip():
        return seller_name.strip()
    read = text_in_query(identity.visible_text, identity.search_query)
    return build_search_query(identity.brand, identity.model, {}, identity.category, read)


def pick_prompt(identity: Identity, query: str, seller_typed: bool, results: list[ShopResult]) -> str:
    lines = [f"The seller says the product is: {query}" if seller_typed else f"Product: {query}"]
    known = ", ".join(f"{k}: {v}" for k, v in (("category", identity.category), ("brand", identity.brand),
                                                ("model", identity.model)) if v)
    if known:
        lines.append(f"Identified from photos of the item as {known}.")
    if identity.visible_text:
        lines.append(f"Text printed on the item: {', '.join(identity.visible_text)}.")
    if identity.model:
        lines.append(f"The model is known: {identity.model} is printed on the item.")
    elif not seller_typed:
        lines.append("No model is printed on the item and the seller didn't name one.")
    lines.append("Results:")
    lines += [f"{r.index}. {r.title} | seller: {r.seller or 'unknown'} | {r.price_text or 'no price'}" for r in results]
    return "\n".join(lines)


# --- I/O --------------------------------------------------------------------------------------


async def ask(source: Source, identity: Identity, query: str, seller_typed: bool) -> tuple[ReferencePrice | None, dict[str, Any]]:
    attempt: dict[str, Any] = {"source": source.name}
    tools = None
    if source.grounded:
        from google.genai import types

        tools = [types.Tool(google_search=types.GoogleSearch())]
    try:
        reply = await generate_json(
            price_prompt(identity, query, seller_typed, source.grounded), SYSTEM_PROMPT, response_schema(), tools=tools,
            timeout_s=PRICE_LOOKUP["estimate_timeout_s"],
        )
    except Exception as e:  # noqa: BLE001  this stage never fails: any error moves on to the next source
        attempt["error"] = f"{type(e).__name__}: {e}"
        return None, attempt
    attempt |= {"model": reply.model, "latency_ms": round(reply.latency_ms), "raw": reply.raw, "grounding": reply.grounding}
    price, problem = answer_to_price(source, reply.raw, reply.grounding, identity.category)
    if problem:
        attempt["rejected"] = problem
    return price, attempt


async def search_shopping(query: str, api_key: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=SERPER_PRICE["timeout_s"]) as client:
        resp = await client.post(
            SERPER_PRICE["endpoint"],
            headers={"X-API-KEY": api_key, "Content-Type": "application/json", "User-Agent": SEARCH["user_agent"]},
            json={"q": query, "gl": SERPER_PRICE["country"], "num": SERPER_PRICE["num"]},
        )
        resp.raise_for_status()
        return resp.json()


async def from_listings(identity: Identity, query: str,
                        seller_typed: bool) -> tuple[ReferencePrice | None, dict[str, Any]]:
    """Source 1: real listings. Gemini checks every result against the item: the exact model when it is known,
    otherwise anything that fits what is known (product line, kind, look), since the scan can't tell similar models
    apart (Jev matched a ThinkPad mouse scan at ~0.9 to photos of three different ThinkPad mice). The median and the
    outlier cut absorb the spread. No reference photo: it comes from our own image search, often one sibling model,
    and Gemini then counted only that model (seen live: the USB-C Compact photo, every other ThinkPad mouse 0.0).
    Never raises: any problem is recorded and the chain moves on.
    One search only: Google Shopping shows one card per product, so searching again by a product's name returned
    the same listings (tried live on the ThinkPad mouse) and cost ~5 s."""
    search_for = query if seller_typed else price_query(identity, None)
    attempt: dict[str, Any] = {"source": LISTINGS_SOURCE, "search_for": search_for}
    if not names_a_product(identity, query if seller_typed else None):
        # Seen live: "computer mouse" priced 12 unrelated mice from $8 to $100. That's not this item's price.
        attempt["rejected"] = "nothing names the product (no seller name, nothing read off the item)"
        return None, attempt
    try:
        with timing.span("serper"):
            payload = await search_shopping(search_for, _require_key("SERPER_API_KEY"))
        results = parse_results(payload, identity.category)
    except Exception as e:  # noqa: BLE001  this stage never fails: any error moves on to the next source
        attempt["error"] = f"{type(e).__name__}: {e}"
        return None, attempt
    attempt["results"] = results
    if not any(r.problem is None for r in results):
        attempt["rejected"] = "no result with a usable CAD price"
        return None, attempt
    try:
        reply = await generate_json(pick_prompt(identity, query, seller_typed, results), PICK_SYSTEM_PROMPT,
                                    pick_schema(), timeout_s=SERPER_PRICE["timeout_s"])
    except Exception as e:  # noqa: BLE001  see above
        attempt["error"] = f"{type(e).__name__}: {e}"
        return None, attempt
    attempt |= {"model": reply.model, "latency_ms": round(reply.latency_ms), "raw": reply.raw}
    amount, kept, outcome = combine_listings(apply_checks(results, reply.raw, widen=identity.model is None))
    attempt |= {"outcome": outcome, "kept": [r.index for r in kept]}
    if amount is None:
        attempt["rejected"] = outcome
        return None, attempt
    if problem := plausible(amount, identity.category):
        attempt["rejected"] = problem
        return None, attempt
    return listings_price(amount, kept), attempt


def log_ready(attempt: dict[str, Any]) -> dict[str, Any]:
    """The attempt with its ShopResults as plain dicts, for the JSON log."""
    if "results" in attempt:
        attempt = attempt | {"results": [asdict(r) for r in attempt["results"]]}
    return attempt


async def look_up(identity: Identity, seller_name: str | None) -> tuple[ReferencePrice, dict[str, Any]]:
    query = baseline_query(identity, seller_name)
    seller_typed = bool(seller_name and seller_name.strip())
    log: dict[str, Any] = {"query": query, "seller_typed": seller_typed, "attempts": []}
    try:
        price, attempt = await asyncio.wait_for(from_listings(identity, query, seller_typed), SERPER_PRICE["budget_s"])
    except asyncio.TimeoutError:
        price, attempt = None, {"source": LISTINGS_SOURCE, "error": f"no listings price within "
                                                                    f"{SERPER_PRICE['budget_s']:.0f} s"}
    log["attempts"].append(log_ready(attempt))
    if price is not None:
        log["source"] = LISTINGS_SOURCE
        return price, log
    for source in (GROUNDED, UNGROUNDED) if GEMINI["search_grounding"] else (UNGROUNDED,):
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
