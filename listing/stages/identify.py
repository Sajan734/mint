"""identify: views -> Identity (Gemini, all views in one call, structured output).

Fixture items that have stubs/identify.json stay offline. Anything else calls Gemini.
Gemini proposes; code enforces the evidence rule: brand and model must each be backed by visible_text.
Unbacked values become null. A product name typed by the seller still takes priority later, in baseline_lookup.
"""

from __future__ import annotations

import asyncio
import functools
import io
import json
import os
import sys
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PIL import Image as PILImage, ImageOps

import timing
from contracts import Identity, RunContext, Views, backed_by_text
from stages._fixture import has_stub, load_stub

LISTING_ROOT = Path(__file__).resolve().parent.parent

GEMINI = {
    # The one model every Gemini call in listing/ uses (identify, listing_text, reference_price, highlight). Set here
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
    "max_side_px": 1536,  # larger images (e.g. phone photos) are shrunk before sending
    "jpeg_quality": 90,
    "max_request_bytes": 19 * 1024 * 1024,  # Gemini's inline-data limit is 20 MB per request
    "field_order": ["category", "visible_text", "brand", "model", "attributes", "search_query", "confidence"],
}

EXIF_ORIENTATION = 274

SYSTEM_PROMPT = """\
You identify a product from several images of one item. They are renders of a 3D scan (Gaussian splat) or \
photos, each preceded by its view id and label. Renders can have soft edges, speckle or small floaters; ignore them.

Fill every field:
- category: the most specific generic product type the images support, e.g. "over-ear wireless headphones", \
not "electronics".
- visible_text: every piece of text you can actually read on the item (brand names, logo text, model numbers, \
labels), copied exactly as printed, one entry per distinct text. Leave out text you infer, expect, or can only \
partly make out. Use an empty list if nothing is legible.
- brand: only if the brand name or logo text is legible and listed in visible_text. Otherwise null. Never \
infer a brand from shape, colour or design.
- model: only if a model name or number is legible and listed in visible_text. Otherwise null, even if you \
recognise the design. Never infer a model from shape, colour or design.
- attributes: short facts visible in the images, with lowercase keys, e.g. colour, material, form_factor.
- search_query: a short web image-search query for a clean product photo of this exact product: brand, model \
and colour when known, otherwise a descriptive query.
- confidence: from 0 to 1, how sure you are of the identification as a whole.\
"""


class MissingKeyError(RuntimeError):
    pass


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
        parts.append(types.Part.from_text(text=f"View {view.view_id}: {view.label}"))
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


def build_search_query(brand: str | None, model: str | None, attributes: dict[str, str], category: str,
                       read: list[str] = ()) -> str:
    """read: other text read off the item to search by (e.g. a product line like "ThinkPad"), placed first."""
    colour = attributes.get("colour") or attributes.get("color")
    named = [t for t in read if not any(backed_by_text(t, [p]) for p in (brand, model) if p)]
    return " ".join(part for part in (*named, brand, model, colour, category) if part)


MIN_QUERY_TEXT_CHARS = 3  # shorter visible text (a lone letter or digit) is found inside any query by chance


def text_in_query(visible: list[str], query: str | None) -> list[str]:
    """The visible text Gemini put in its own search query: what it read and judged to name the product."""
    return [t for t in visible
            if query and sum(ch.isalnum() for ch in t) >= MIN_QUERY_TEXT_CHARS and backed_by_text(t, [query])]


def enforce_evidence(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Applies the evidence rule to Gemini's raw answer. Returns Identity fields and notes on what changed."""
    notes: list[str] = []
    fields = {k: raw[k] for k in Identity.model_fields if k in raw}
    extra = sorted(set(raw) - set(Identity.model_fields))
    if extra:
        notes.append(f"ignored unexpected fields: {', '.join(extra)}")

    visible = [t.strip() for t in raw.get("visible_text") or [] if isinstance(t, str) and t.strip()]
    attributes = {str(k).strip().lower(): str(v).strip() for k, v in (raw.get("attributes") or {}).items() if str(v).strip()}
    category = _clean(raw.get("category")) or ""
    brand, model = _clean(raw.get("brand")), _clean(raw.get("model"))

    if brand and not backed_by_text(brand, visible):
        notes.append(f"dropped brand {brand!r}: not in visible_text")
        brand = None
    if model and not backed_by_text(model, visible):
        notes.append(f"dropped model {model!r}: not in visible_text")
        model = None

    # Gemini's query can carry a brand or model guess even when it nulls those fields itself,
    # so it is kept only when both are backed. A rebuilt query keeps the visible text Gemini's query used:
    # with "ThinkPad" printed on a mouse it may answer brand "Lenovo" (dropped, not on the item), and the
    # query must still say ThinkPad, or the reference photo search has nothing specific to look for.
    query = _clean(raw.get("search_query"))
    if not (brand and model and query):
        rebuilt = build_search_query(brand, model, attributes, category, text_in_query(visible, query))
        if rebuilt != query:
            notes.append(f"search_query rebuilt as {rebuilt!r} (was {query!r})")
        query = rebuilt

    fields.update(
        category=category, brand=brand, model=model, visible_text=visible, attributes=attributes, search_query=query
    )
    return fields, notes


def to_identity(raw: dict[str, Any]) -> tuple[Identity, list[str]]:
    fields, notes = enforce_evidence(raw)
    return Identity.model_validate(fields), notes


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
    it (the pipeline runs this during the render). Never raises: without a key, the call that needs it will say so."""
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


async def identify(ctx: RunContext, views: Views) -> Identity:
    if has_stub(ctx, "identify"):
        return load_stub(ctx, "identify", Identity)
    result = await call_gemini(views)
    identity, notes = to_identity(result.raw)
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    (ctx.run_dir / "identify_raw.json").write_text(
        json.dumps(
            {
                "model": result.model,
                "latency_ms": round(result.latency_ms),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "image_notes": result.image_notes,
                "evidence_notes": notes,
                "raw": result.raw,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return identity
