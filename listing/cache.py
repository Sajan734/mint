"""Cached stage outputs keyed by item id + stage, read first when DEMO_MODE=1."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def _path(cache_dir: Path, item_id: str, stage: str) -> Path:
    return cache_dir / item_id / f"{stage}.json"


def get(cache_dir: Path, item_id: str, stage: str, model: type[M]) -> M | None:
    path = _path(cache_dir, item_id, stage)
    if not path.is_file():
        return None
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def put(cache_dir: Path, item_id: str, stage: str, obj: BaseModel) -> None:
    path = _path(cache_dir, item_id, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
