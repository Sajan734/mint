"""identify: views -> Identity (Gemini, all views in one call). Stub: returns fixture identity."""

from __future__ import annotations

from contracts import Identity, RunContext, Views
from stages._fixture import load_stub


async def identify(ctx: RunContext, views: Views) -> Identity:
    # TODO: one Gemini call with all views and an Identity response schema.
    return load_stub(ctx, "identify", Identity)
