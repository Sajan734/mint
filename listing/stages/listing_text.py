"""listing_text: Identity -> ListingDraft (Gemini, no price or condition). Stub: fixture draft."""

from __future__ import annotations

from contracts import Identity, ListingDraft, RunContext
from stages._fixture import load_stub


async def listing_text(ctx: RunContext, identity: Identity) -> ListingDraft:
    # TODO: Gemini call with a ListingDraft response schema.
    return load_stub(ctx, "listing_text", ListingDraft)
