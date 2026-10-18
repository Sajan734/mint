"""identify: photos (+ the seller's name) -> Identity: what the product is, as specific as the evidence allows.

Fixture items that have stubs/identify.json stay offline. Otherwise, in parallel:
  read  one Gemini call with every photo: the text printed on the item, the product type, and Gemini's best guess at
        brand and model
  lens  Google Lens on two photos (stages/lens.py): titles of visually matching products
then fuse: one text-only Gemini call weighs the read, the seller's name and the Lens titles into a candidate brand,
model and product type (skipped when there is neither a Lens match nor a seller name). Code decides what is claimed
(decide): a value is backed when it is printed on the item, in the seller's name, or in enough Lens titles from
enough different sources. A brand needs one kind of backing, an exact model two. Otherwise the most specific
backed name is used ("Logitech wireless mouse"), never a guess. Identity.evidence says what backed what.
"""

from __future__ import annotations

import asyncio
import functools
import io
import json
import os
import re
import sys
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PIL import Image as PILImage, ImageOps

import timing
from contracts import Identity, IdentityCandidate, RunContext, Views, backed_by_text, product_name
from stages._fixture import has_stub, load_stub

LISTING_ROOT = Path(__file__).resolve().parent.parent

GEMINI = {
    # The one model every Gemini call in listing/ uses (identify, listing_text, reference_price). Set here
    # only: a GEMINI_MODEL in the environment is ignored, because it differed per machine (the local .env vs the
    # Modal secret) and quietly put stages on models nobody chose. The free tier's daily limit is per model.
    "model": "gemini-3.5-flash-lite",
    # Google Search grounding for reference_price's looked-up new price. Off: our free-tier project (htv11) gets 0
    # grounding requests a day on Gemini 3 and newer, and the Gemini 2.5 models that have grounding are "no longer
    # available to new users" (404), so the attempt could only fail and waste requests. Turn on with billing.
    "search_grounding": False,
    "temperature": 0.0,
    "timeout_s": 60,
    "max_retries": 1,
    "retry_client_codes": {408, 429},  # other 4xx errors are not retried
    # On 429 (the free tier allows 15 requests a minute per model) wait what Gemini asks, up to this, then retry.
    "max_retry_wait_s": 20.0,
    "max_side_px": 1536,  # larger images (e.g. phone photos) are shrunk before sending
    "jpeg_quality": 90,
    "max_request_bytes": 19 * 1024 * 1024,  # Gemini's inline-data limit is 20 MB per request
    "field_order": ["category", "visible_text", "brand", "model", "attributes", "search_query", "confidence"],
}

EXIF_ORIENTATION = 274

SYSTEM_PROMPT = """\
You identify a product from several photos of one item, each preceded by its photo id.

Fill every field:
- category: the most specific generic product type the photos support, e.g. "wireless ergonomic mouse" or \
"over-ear wireless headphones", not "electronics" and not just a colour.
- visible_text: every piece of text you can actually read on the item (brand names, logo text, model names and \
numbers, labels), copied exactly as printed, one entry per distinct text. Leave out text you infer, expect, or can \
only partly make out. Use an empty list if nothing is legible.
- brand: your best identification of the brand, from printed text or from the design. null if you can't tell.
- model: your best identification of the model, without the brand: the name or number that tells this product \
apart from the brand's other products of this type. A product line or series that covers many different products is \
not a model. null if you can't tell.
- attributes: short facts visible in the photos, with lowercase keys, e.g. colour, material, form_factor.
- search_query: a short web search query for this product: brand, model and type when known.
- confidence: from 0 to 1, how sure you are of the identification as a whole.
Brand and model guesses are checked against other evidence before anything is claimed, so give your real best \
guess, but never copy a guess into visible_text.\
"""

FUSE_PROMPT = """\
You decide what a second-hand product is from the evidence about one item:
- text read off the item's photos (exact, but often partial), and the product type seen in the photos
- the seller's name for it, when they typed one
- titles of visually similar products found by an image search of the photos. Many titles are other products \
that merely look alike; trust what several titles agree on and what matches the printed text.

Answer:
- brand: the brand (or the product line printed on it, if that is what the evidence names). null if unclear.
- model: the model without the brand (the name or number that tells this product apart from the brand's other \
products of this type), only if the evidence points to one model. A product line or series that covers many \
different products is not a model. null otherwise.
- product_type: the specific generic type, e.g. "wireless ergonomic mouse". Not a colour.\
"""


class MissingKeyError(RuntimeError):
    pass


IDENTIFY = {
    "lens_min_titles": 3,  # Lens backs a value when this many of its titles contain it ...
    "lens_min_sources": 2,  # ... from at least this many different sites
    "model_min_kinds": 2,  # an exact model needs this many kinds of backing (printed, seller, Lens)
    # A model claim needs a digit or this many words: one plain word ("ThinkPad") is usually a product line covering
    # many products, which made baseline and price searches find the wrong ones.
    "model_min_words": 2,
    "lens_budget_s": 10.0,  # identify goes on without Lens after this
    "lens_titles_in_prompt": 25,
    "fuse_timeout_s": 15.0,
}


@dataclass(frozen=True)
class GeminiResult:
    raw: dict[str, Any]
    model: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    image_notes: list[str] = field(default_factory=list)


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else LISTING_ROOT / p


def load_image(path: Path) -> tuple[bytes, str, str | None]:
    """Returns (bytes, mime type, note). Rotates upright from EXIF and shrinks oversized images."""
    data = path.read_bytes()
    with PILImage.open(io.BytesIO(data)) as img:
        fmt, out, notes = img.format, img, []
        if img.getexif().get(EXIF_ORIENTATION, 1) != 1:
            out = ImageOps.exif_transpose(img)
            notes.append("rotated upright")
        if max(out.size) > GEMINI["max_side_px"] or fmt not in ("PNG", "JPEG"):
            w0, h0 = out.size
            out = out.copy()
            out.thumbnail((GEMINI["max_side_px"], GEMINI["max_side_px"]), PILImage.Resampling.LANCZOS)
            if (w0, h0) != out.size:
                notes.append(f"shrunk from {w0}x{h0}")
            if fmt not in ("PNG", "JPEG"):
                notes.append(f"converted from {fmt}")
                fmt = "JPEG"
        if notes:
            buf = io.BytesIO()
            if fmt == "JPEG":
                out.convert("RGB").save(buf, format="JPEG", quality=GEMINI["jpeg_quality"])
            else:
                out.save(buf, format="PNG")
            data = buf.getvalue()
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return data, mime, f"{path.name}: {', '.join(notes)}" if notes else None


def build_contents(views: Views) -> tuple[list[Any], list[str]]:
    from google.genai import types

    parts: list[Any] = []
    notes: list[str] = []
    total = 0
    for view in views.views:
        data, mime, note = load_image(resolve(view.image_path))
        total += len(data)
        if note:
            notes.append(note)
        parts.append(types.Part.from_text(text=f"Photo {view.view_id}:"))
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    if total > GEMINI["max_request_bytes"]:
        raise ValueError(f"{len(views.views)} images total {total / 2**20:.1f} MiB, over Gemini's inline limit")
    parts.append(types.Part.from_text(text="Identify this item."))
    return parts, notes


def _strip_defaults(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_defaults(v) for k, v in node.items() if k != "default"}
    if isinstance(node, list):
        return [_strip_defaults(v) for v in node]
    return node


def response_schema() -> dict[str, Any]:
    """Identity's JSON schema, every field required, visible_text asked before brand and model."""
    schema = _strip_defaults(Identity.model_json_schema())
    props = schema["properties"]
    schema["properties"] = {name: props[name] for name in GEMINI["field_order"]}
    schema["required"] = list(GEMINI["field_order"])
    return schema


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


RETRY_DELAY = re.compile(r"retry in ([\d.]+)\s*s", re.IGNORECASE)


def retry_wait_s(error: Exception) -> float:
    """How long a 429 asks us to wait ("Please retry in 14.04s"), capped; 0 for anything else."""
    if getattr(error, "code", None) != 429:
        return 0.0
    match = RETRY_DELAY.search(str(error))
    return min(float(match.group(1)), GEMINI["max_retry_wait_s"]) if match else 1.0


MIN_QUERY_TEXT_CHARS = 3  # shorter visible text (a lone letter or digit) is found inside any query by chance


def text_in_query(visible: list[str], query: str | None) -> list[str]:
    """The visible text Gemini put in its own search query: what it read and judged to name the product."""
    return [t for t in visible
            if query and sum(ch.isalnum() for ch in t) >= MIN_QUERY_TEXT_CHARS and backed_by_text(t, [query])]


def read_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Gemini's read, cleaned: visible_text, category, attributes, brand and model guesses, query, confidence."""
    visible = [t.strip() for t in raw.get("visible_text") or [] if isinstance(t, str) and t.strip()]
    attributes = {str(k).strip().lower(): str(v).strip() for k, v in (raw.get("attributes") or {}).items()
                  if str(v).strip()}
    confidence = raw.get("confidence")
    return {
        "category": _clean(raw.get("category")) or "item",
        "visible_text": list(dict.fromkeys(visible)),
        "attributes": attributes,
        "brand": _clean(raw.get("brand")),
        "model": _clean(raw.get("model")),
        "search_query": _clean(raw.get("search_query")),
        "confidence": float(confidence) if isinstance(confidence, (int, float)) and 0 <= confidence <= 1 else 0.5,
    }


def backing(value: str | None, visible: list[str], seller_name: str | None, matches: list[Any]) -> list[str]:
    """The kinds of evidence behind `value`: "printed", "seller", "lens (n titles, m sources)"."""
    from stages.lens import support

    if not value:
        return []
    kinds = []
    if backed_by_text(value, visible):
        kinds.append("printed")
    if seller_name and seller_name.strip() and backed_by_text(value, [seller_name]):
        kinds.append("seller")
    titles, sources = support(value, matches)
    if titles >= IDENTIFY["lens_min_titles"] and sources >= IDENTIFY["lens_min_sources"]:
        kinds.append(f"lens ({titles} titles, {sources} sources)")
    return kinds


def specific_enough(model: str) -> bool:
    return any(ch.isdigit() for ch in model) or len(re.findall(r"[^\W_]+", model)) >= IDENTIFY["model_min_words"]


def decide(read: dict[str, Any], candidate: dict[str, Any] | None, seller_name: str | None,
           matches: list[Any]) -> tuple[Identity, list[str]]:
    """What is claimed, from the read, the fused candidate, the seller's name and the Lens matches."""
    candidate = candidate or {}
    visible, notes, evidence = read["visible_text"], [], []
    category = _clean(candidate.get("product_type")) or read["category"]

    # brand: the fused answer, Gemini's read, or a product line printed on the item that its query used (but not the
    # printed model itself: "MX Master 3S" on the item isn't a brand)
    model_guesses = [m for m in (_clean(candidate.get("model")), read["model"]) if m]
    printed_lines = [t for t in text_in_query(visible, read["search_query"])
                     if not any(backed_by_text(m, [t]) for m in model_guesses)]
    brands = [_clean(candidate.get("brand")), read["brand"], *printed_lines]
    brand = None
    for value in dict.fromkeys(b for b in brands if b):
        if kinds := backing(value, visible, seller_name, matches):
            brand = value
            evidence.append(f"brand {value!r}: {', '.join(kinds)}")
            break
        notes.append(f"brand {value!r} not claimed: nothing backs it")

    model = None
    for value in dict.fromkeys(m for m in (_clean(candidate.get("model")), read["model"]) if m):
        if not specific_enough(value):
            notes.append(f"model {value!r} not claimed: one plain word is usually a product line, not a model")
            continue
        kinds = backing(value, visible, seller_name, matches)
        if brand and len(kinds) >= IDENTIFY["model_min_kinds"]:
            model = value
            evidence.append(f"model {value!r}: {', '.join(kinds)}")
            break
        notes.append(f"model {value!r} not claimed: backed by {', '.join(kinds) or 'nothing'}"
                     f"{'' if brand else ' and no brand is backed'}")

    name = product_name(brand, model, category)
    identity = Identity(
        category=category, brand=brand, model=model, visible_text=visible, attributes=read["attributes"],
        product_name=name, specificity="model" if model else "brand" if brand else "type", evidence=evidence,
        search_query=search_query(name, category), confidence=read["confidence"],
    )
    return identity, notes


def search_query(name: str, category: str) -> str:
    """The product name with its type, unless the name already says it: searches for a reference photo, prices and
    sources then stay within this kind of product even when the model is broad (a ThinkPad mouse, not a laptop)."""
    return name if backed_by_text(category, [name]) else f"{name} {category}"


def fuse_prompt(read: dict[str, Any], seller_name: str | None, matches: list[Any]) -> str:
    from stages.lens import titles_for_prompt

    lines = [f"Product type seen in the photos: {read['category']}",
             f"Text read off the item: {'; '.join(read['visible_text']) or '(nothing legible)'}"]
    if read["brand"] or read["model"]:
        lines.append(f"Guess from the photos alone: {' '.join(v for v in (read['brand'], read['model']) if v)}")
    if seller_name and seller_name.strip():
        lines.append(f"The seller calls it: {seller_name.strip()}")
    titles = titles_for_prompt(matches, IDENTIFY["lens_titles_in_prompt"])
    lines.append("Visually similar products found by image search:" if titles else "Image search found nothing.")
    lines += [f"- {t}" for t in titles]
    return "\n".join(lines)


def _api_key() -> str:
    load_dotenv(LISTING_ROOT.parent / ".env")  # the repo-wide .env
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise MissingKeyError("GEMINI_API_KEY is missing: add it to the repo-root .env")
    return key


@functools.cache
def _warn_ignored_model(value: str) -> None:
    print(f"[gemini] ignoring GEMINI_MODEL={value} from the environment: every listing stage uses "
          f"{GEMINI['model']}, set in listing/stages/identify.py. Remove GEMINI_MODEL from .env.", file=sys.stderr)


def gemini_model() -> str:
    """The Gemini model for every listing stage: GEMINI["model"], whatever GEMINI_MODEL says."""
    other = os.environ.get("GEMINI_MODEL", "").strip()
    if other and other != GEMINI["model"]:
        _warn_ignored_model(other)
    return GEMINI["model"]


# One google-genai client per event loop and key. Making one costs ~0.5 s (TLS setup), and every Gemini call made a
# new one; its async HTTP client belongs to the loop that first uses it, so clients aren't shared across loops.
_CLIENTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, Any]] = weakref.WeakKeyDictionary()


def _new_client(key: str) -> Any:
    from google import genai

    return genai.Client(api_key=key)


def gemini_client(key: str) -> Any:
    """This event loop's client for `key`, made on first use."""
    clients = _CLIENTS.setdefault(asyncio.get_running_loop(), {})
    if key not in clients:
        clients[key] = _new_client(key)
    return clients[key]


async def warm_gemini() -> None:
    """Imports google-genai and makes this loop's client in a thread, so the first Gemini call doesn't pay ~1 s for
    it (the pipeline runs this while the photos load). Never raises: without a key, the call that needs it will say so."""
    try:
        key = _api_key()
    except MissingKeyError:
        return
    clients = _CLIENTS.setdefault(asyncio.get_running_loop(), {})
    if key not in clients:
        client = await asyncio.to_thread(_new_client, key)
        clients.setdefault(key, client)


async def call_gemini(views: Views, model: str | None = None) -> GeminiResult:
    """`model` is for experiments (scripts/try_identify.py --model); the pipeline always uses gemini_model()."""
    from google.genai import errors, types

    key = _api_key()
    model = model or gemini_model()
    contents, image_notes = build_contents(views)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=GEMINI["temperature"],
        response_mime_type="application/json",
        response_json_schema=response_schema(),
    )
    client = gemini_client(key)
    last_error: Exception | None = None
    start = time.perf_counter()
    with timing.span("gemini"):
        for _attempt in range(GEMINI["max_retries"] + 1):
            try:
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(model=model, contents=contents, config=config),
                    timeout=GEMINI["timeout_s"],
                )
                break
            except errors.ClientError as e:
                if e.code not in GEMINI["retry_client_codes"]:
                    raise
                last_error = e
                await asyncio.sleep(retry_wait_s(e))
            except (errors.APIError, asyncio.TimeoutError) as e:
                last_error = e
        else:
            raise RuntimeError(
                f"Gemini failed after {GEMINI['max_retries'] + 1} attempts: {last_error!r}") from last_error
    latency_ms = (time.perf_counter() - start) * 1000

    if not resp.text:
        raise RuntimeError(f"Gemini returned no text (finish reason: {resp.candidates and resp.candidates[0].finish_reason})")
    usage = resp.usage_metadata
    return GeminiResult(
        raw=json.loads(resp.text),
        model=resp.model_version or model,
        latency_ms=latency_ms,
        input_tokens=usage.prompt_token_count if usage else None,
        output_tokens=usage.candidates_token_count if usage else None,
        image_notes=image_notes,
    )


async def fuse(read: dict[str, Any], seller_name: str | None, matches: list[Any]) -> tuple[dict | None, dict]:
    """One text-only Gemini call -> a candidate (brand, model, product_type). Never raises: None on failure."""
    from gemini import contract_schema, generate_json

    log: dict[str, Any] = {}
    try:
        reply = await generate_json(fuse_prompt(read, seller_name, matches), FUSE_PROMPT,
                                    contract_schema(IdentityCandidate, ["brand", "model", "product_type"]),
                                    timeout_s=IDENTIFY["fuse_timeout_s"])
    except MissingKeyError:
        raise
    except Exception as e:  # noqa: BLE001  the read alone still identifies the item
        log["error"] = f"{type(e).__name__}: {e}"
        return None, log
    log |= {"model": reply.model, "latency_ms": round(reply.latency_ms), "raw": reply.raw}
    return reply.raw, log


async def lens_within_budget(views: Views, item_id: str) -> tuple[list[Any], dict[str, Any]]:
    from stages.lens import lens_matches

    try:
        return await asyncio.wait_for(lens_matches(views, item_id), IDENTIFY["lens_budget_s"])
    except asyncio.TimeoutError:
        return [], {"error": f"no Lens answer within {IDENTIFY['lens_budget_s']:.0f} s"}


async def identify(ctx: RunContext, views: Views, seller_name: str | None = None) -> Identity:
    if has_stub(ctx, "identify"):
        return load_stub(ctx, "identify", Identity)
    result, (matches, lens_log) = await asyncio.gather(call_gemini(views), lens_within_budget(views, ctx.item_id))
    read = read_fields(result.raw)
    identity, notes = decide(read, None, seller_name, matches)
    fuse_log: dict[str, Any] = {"skipped": "the read's own guesses already settle the model"}
    if identity.specificity != "model":  # fusing can only help when the read alone didn't reach a model
        if matches or (seller_name and seller_name.strip()):
            candidate, fuse_log = await fuse(read, seller_name, matches)
            identity, notes = decide(read, candidate, seller_name, matches)
        else:
            fuse_log = {"skipped": "no Lens match and no seller name"}
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    (ctx.run_dir / "identify_raw.json").write_text(
        json.dumps(
            {
                "model": result.model,
                "latency_ms": round(result.latency_ms),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "image_notes": result.image_notes,
                "raw": result.raw,
                "lens": lens_log,
                "fuse": fuse_log,
                "decision_notes": notes,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return identity
