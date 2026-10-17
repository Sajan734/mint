import os
from uuid import uuid4

import pytest

from buyer_agent.retention import prune_runs

DAY = 86400
NOW = 1_000_000_000.0


def mk(root, name, age_days, files=("a.json",)):
    d = root / name
    d.mkdir()
    for f in files:
        p = d / f
        p.write_text("x")
        os.utime(p, (NOW - age_days * DAY,) * 2)
    os.utime(d, (NOW - age_days * DAY,) * 2)
    return d


def test_prune_deletes_only_uuid_dirs_older_than_14_days(tmp_path):
    old, fresh, mixed = (mk(tmp_path, str(uuid4()), a) for a in (20, 3, 20))
    os.utime(mixed / "a.json", (NOW - DAY,) * 2)  # newest file is recent -> kept
    assert prune_runs(tmp_path, 14, NOW) == 1
    assert not old.exists() and fresh.exists() and mixed.exists()


def test_prune_ignores_symlinks_and_non_uuid(tmp_path):
    other = tmp_path.parent / f"{tmp_path.name}_other"
    other.mkdir()
    (other / "keep.txt").write_text("x")
    plain = mk(tmp_path, "notes", 99)
    link = tmp_path / str(uuid4())
    try:
        link.symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted")
    assert prune_runs(tmp_path, 14, NOW + 99 * DAY) == 0
    assert plain.exists() and link.is_symlink() and (other / "keep.txt").exists()


def test_prune_missing_root_is_noop(tmp_path):
    assert prune_runs(tmp_path / "nope", 14, NOW) == 0
