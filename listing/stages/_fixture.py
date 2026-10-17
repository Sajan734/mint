"""Loads hand-written stub outputs from fixtures/<item>/stubs/<stage>.json until stages are real."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from contracts import RunContext

M = TypeVar("M", bound=BaseModel)


def stub_path(ctx: RunContext, stage: str) -> Path:
    return ctx.item_dir / "stubs" / f"{stage}.json"


def has_stub(ctx: RunContext, stage: str) -> bool:
    """Implemented stages use the fixture's stub when it has one, so fixture runs stay offline."""
    return stub_path(ctx, stage).is_file()


def load_stub(ctx: RunContext, stage: str, model: type[M]) -> M:
    path = stub_path(ctx, stage)
    if not path.is_file():
        raise FileNotFoundError(
            f"stage {stage!r} is stubbed and has no fixture for item {ctx.item_id!r}: {path}"
        )
    return model.model_validate_json(path.read_text(encoding="utf-8"))
