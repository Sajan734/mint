"""baseline_lookup: seller's name or Identity.search_query -> Baseline. Stub: fixture image."""

from __future__ import annotations

from contracts import Baseline, Identity, RunContext
from stages._fixture import load_stub


def baseline_query(identity: Identity, seller_name: str | None) -> str:
    if seller_name and seller_name.strip():
        return seller_name.strip()
    return identity.search_query


async def baseline_lookup(ctx: RunContext, identity: Identity, seller_name: str | None) -> Baseline:
    query = baseline_query(identity, seller_name)
    # TODO: image search for `query`.
    stub = load_stub(ctx, "baseline_lookup", Baseline)
    return stub.model_copy(update={"query": query})
