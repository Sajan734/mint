"""Replay-pin CI gate (U29, AM-27): `python -m eval.ci_check`.

1. Any `model` field in tests/fixtures/**/*.json that is not the pin -> exit 1, file named.
2. pytest -q -m "not live". Exit code is the worse of both.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from buyer_agent.config import JEV_MODEL_PIN

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("eval.ci_check")


def _models(node: Any) -> list[Any]:
    if isinstance(node, dict):
        found = [node["model"]] if "model" in node else []
        return found + [m for v in node.values() for m in _models(v)]
    if isinstance(node, list):
        return [m for v in node for m in _models(v)]
    return []


def bad_fixtures(root: Path = ROOT) -> list[Path]:
    bad = []
    for path in sorted((root / "tests" / "fixtures").glob("**/*.json")):
        try:
            models = _models(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            bad.append(path)  # an unreadable fixture is not trustworthy either
            continue
        if any(m != JEV_MODEL_PIN for m in models):
            bad.append(path)
    return bad


def main(root: Path = ROOT, run_tests: bool = True) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    bad = bad_fixtures(root)
    for p in bad:
        log.error("fixture model != %s: %s", JEV_MODEL_PIN, p)
    code = 1 if bad else 0
    if run_tests:
        cmd = [sys.executable, "-m", "pytest", "-q", "-m", "not live"]
        r = subprocess.run(cmd, cwd=root, check=False)
        code = max(code, r.returncode)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
