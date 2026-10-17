"""Run-folder retention (AM-20). Only UUID-named real directories are ever deleted."""

import os
import shutil
from pathlib import Path
from uuid import UUID


def _is_uuid(name: str) -> bool:
    try:
        return str(UUID(name)) == name.lower()
    except ValueError:
        return False


def _newest_mtime(folder: Path) -> float:
    newest = folder.stat().st_mtime
    for root, _dirs, files in os.walk(folder, followlinks=False):
        for f in files:
            newest = max(newest, os.lstat(os.path.join(root, f)).st_mtime)
    return newest


def prune_runs(runs_root: Path, max_age_days: int, now: float) -> int:
    """Delete UUID run folders whose newest file is older than the limit. Returns count."""
    if not runs_root.is_dir():
        return 0
    limit = now - max_age_days * 86400
    removed = 0
    for entry in runs_root.iterdir():
        if entry.is_symlink() or not entry.is_dir() or not _is_uuid(entry.name):
            continue
        if _newest_mtime(entry) < limit:
            shutil.rmtree(entry)
            removed += 1
    return removed
