"""One structured-output Gemini call with a timeout and one retry, shared by the text-only stages.

Uses identify's GEMINI settings (including the one model every stage uses) and key loading. The caller passes a
JSON schema built from contracts.py;
the reply is parsed JSON, never free text.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import timing
from stages.identify import GEMINI, _api_key, _strip_defaults, gemini_client, gemini_model, retry_wait_s


@dataclass(frozen=True)
class GeminiReply:
    raw: dict[str, Any]
    model: str
    latency_ms: float
    grounding: list[dict[str, str | None]] = field(default_factory=list)  # web sources Google Search used


def contract_schema(model: type, fields: list[str]) -> dict[str, Any]:
    """`model`'s JSON schema cut down to `fields`, in that order, all required."""
    schema = _strip_defaults(model.model_json_schema())
    props = schema["properties"]
    schema["properties"] = {name: props[name] for name in fields}
    schema["required"] = list(fields)
    return schema


def grounding_sources(resp: Any) -> list[dict[str, str | None]]:
    """Web sources from the grounding metadata. Empty when the model answered without searching."""
    candidates = getattr(resp, "candidates", None) or []
    meta = getattr(candidates[0], "grounding_metadata", None) if candidates else None
    sources: dict[str, dict[str, str | None]] = {}
    for chunk in getattr(meta, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        if web is not None and web.uri:
            sources.setdefault(web.uri, {"uri": web.uri, "title": web.title, "domain": web.domain})
    return list(sources.values())


async def generate_json(
    contents: Any,
    system_prompt: str,
    schema: dict[str, Any],
    *,
    tools: list[Any] | None = None,
    temperature: float | None = None,
    timeout_s: float | None = None,
) -> GeminiReply:
    """timeout_s: per attempt (default GEMINI["timeout_s"]); a stage with a fallback passes less, so one slow call
    can't stall the listing."""
    from google.genai import errors, types

    key = _api_key()
    model = gemini_model()
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=GEMINI["temperature"] if temperature is None else temperature,
        response_mime_type="application/json",
        response_json_schema=schema,
        tools=tools,
    )
    client = gemini_client(key)
    last_error: Exception | None = None
    start = time.perf_counter()
    with timing.span("gemini"):
        for _attempt in range(GEMINI["max_retries"] + 1):
            try:
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(model=model, contents=contents, config=config),
                    timeout=GEMINI["timeout_s"] if timeout_s is None else timeout_s,
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
    return GeminiReply(
        raw=json.loads(resp.text),
        model=resp.model_version or model,
        latency_ms=latency_ms,
        grounding=grounding_sources(resp),
    )
