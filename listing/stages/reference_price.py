"""reference_price: Identity -> ReferencePrice (Jev). Stub: fixture price."""

from __future__ import annotations

from contracts import Identity, ReferencePrice, RunContext
from stages._fixture import load_stub


async def reference_price(ctx: RunContext, identity: Identity) -> ReferencePrice:
    # TODO: real price lookup.
    return load_stub(ctx, "reference_price", ReferencePrice)
