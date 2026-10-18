"""Cached stage outputs for DEMO_MODE, keyed by item id, stage and a hash of everything the stage was given.

The key covers the stage's inputs (upstream outputs, the seller's name, the asking price) and the run settings, so
a changed input is a miss rather than a stale hit, and replaying a run hits every stage. Files a stage writes next
to its JSON are cached with it and put back when they've gone missing.
Layout: <cache_dir>/<item>/<stage>.<key>.json, and <stage>.<key>.files/ with a files.json manifest.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)

LISTING_ROOT = Path(__file__).resolve().parent
KEY_HEX = 16


def _portable(value: Any) -> Any:
    """JSON-ready form of a key part. Paths under listing/ are relative, so every checkout gets the same key."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        try:
            return value.resolve().relative_to(LISTING_ROOT).as_posix()
        except ValueError:
            return value.as_posix()
    return value


def key(*parts: Any) -> str:
    text = json.dumps([_portable(p) for p in parts], sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:KEY_HEX]


def _path(cache_dir: Path, item_id: str, stage: str, k: str) -> Path:
    return cache_dir / item_id / f"{stage}.{k}.json"


def _files_dir(cache_dir: Path, item_id: str, stage: str, k: str) -> Path:
    return cache_dir / item_id / f"{stage}.{k}.files"


def _listing_path(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else LISTING_ROOT / p


def get(cache_dir: Path, item_id: str, stage: str, k: str, model: type[M]) -> M | None:
    """The cached output, with its files put back where they were written if they're gone; None on a miss."""
    path = _path(cache_dir, item_id, stage, k)
    if not path.is_file():
        return None
    try:
        result = model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as e:  # written by an older contract: recompute rather than fail the demo
        print(f"[cache] ignoring {path.name}: {e.errors()[0]['msg']}", file=sys.stderr)
        return None
    files = _files_dir(cache_dir, item_id, stage, k)
    manifest = files / "files.json"
    if manifest.is_file():
        for stored, original in json.loads(manifest.read_text(encoding="utf-8")).items():
            target = _listing_path(original)
            if not target.exists() and (files / stored).is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(files / stored, target)
    return result


def put(cache_dir: Path, item_id: str, stage: str, k: str, obj: BaseModel, files: list[str] = ()) -> None:
    """Caches the output and copies of `files` (paths as the output records them: relative to listing/ or absolute)."""
    path = _path(cache_dir, item_id, stage, k)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    present = [f for f in files if f and _listing_path(f).is_file()]
    if present:
        folder = _files_dir(cache_dir, item_id, stage, k)
        folder.mkdir(parents=True, exist_ok=True)
        manifest = {}
        for i, original in enumerate(present):
            stored = f"{i}_{Path(original).name}"
            shutil.copy2(_listing_path(original), folder / stored)
            manifest[stored] = original
        (folder / "files.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
