"""Loads hand-written stub outputs from fixtures/<item>/stubs/<stage>.json until stages are real."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from contracts import RunContext

M = TypeVar("M", bound=BaseModel)


def load_stub(ctx: RunContext, stage: str, model: type[M]) -> M:
    path = ctx.item_dir / "stubs" / f"{stage}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"stage {stage!r} is stubbed and has no fixture for item {ctx.item_id!r}: {path}"
        )
    return model.model_validate_json(path.read_text(encoding="utf-8"))
