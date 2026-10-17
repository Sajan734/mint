"""condition: views + baseline -> Condition (Jev). Stub: fixture condition."""

from __future__ import annotations

from contracts import Baseline, Condition, RunContext, Views
from stages._fixture import load_stub


async def condition(ctx: RunContext, views: Views, baseline: Baseline) -> Condition:
    # TODO: one Jev request per view, aggregate with the 2nd-highest value.
    return load_stub(ctx, "condition", Condition)
