"""Frozen-threshold pre-registration (AM-23/24). `python -m eval.prereg --hash | --write`."""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from buyer_agent.aggregate import Thresholds

PREREG_PATH = Path(__file__).resolve().parent / "PREREG.md"
_HASH_RE = re.compile(r"thresholds_sha256:\s*([0-9a-f]{64})")
_BLOCK = r"```json {name}\s*\n(.*?)\n```"

TEMPLATE = """# PREREG: buyer-agent evaluation (v2)
Frozen before the first PASLCD run. Approved by: <user>, <date>. results.md quotes this file's commit.

## Version history
v2: the verdict is strictly binary (same / different). Replaced `same` (0.25) with `match_min`
(0.70): same iff match_score = 1 - strongest category evidence >= 0.70. The 0.70 was chosen from
mismatch and synthetic data only; there is no real true-match data yet. If real matches get
rejected, loosen it to 0.60 and make a new version (v3).
v1 (superseded): sha256 37d9ed4f3fcf050453430871d00961eafbc45b7a4bd0029373665a3288bd3187.

## Frozen thresholds
thresholds_sha256: {sha}
```json thresholds
{thresholds}
```

## Split
Tune: Printing_area, Porch. Held-out: Pots, Zen. Held-out runs only after this file is committed.
A threshold change creates a new version of this file, re-runs tune, and labels all later results "tuned on tune split".

## Strata cut-offs (changed cases)
small < 2% mask area, medium 2-10%, large > 10%. Merges: <filled by U30 log>.

## Pre-registered cases
```json cases
[]
```

## Pass rule (stated before running)
Wrong = changed/different case -> same, or same case -> different. S2 passes only with zero wrong in all 3 runs.
Report n, Wilson 95% intervals, false-same rate on changed, run spread. No accuracy claim.

## Eye-check log (pair validity only, never labels)
<case>: <what was checked>, <by>, <date>
"""


class Prereg(BaseModel):
    model_config = ConfigDict(frozen=True)
    thresholds_sha256: str
    thresholds: dict[str, Any]
    cases: list[dict[str, Any]]


class PreregMismatch(ValueError):
    pass


def _canonical(th: Thresholds) -> str:
    return json.dumps(th.model_dump(), sort_keys=True, separators=(",", ":"))


def thresholds_sha256(th: Thresholds) -> str:
    return hashlib.sha256(_canonical(th).encode()).hexdigest()


def render_prereg(th: Thresholds | None = None) -> str:
    th = th or Thresholds()
    return TEMPLATE.format(
        sha=thresholds_sha256(th), thresholds=json.dumps(th.model_dump(), sort_keys=True, indent=2)
    )


def _block(text: str, name: str) -> Any:
    m = re.search(_BLOCK.format(name=name), text, re.DOTALL)
    if not m:
        raise PreregMismatch(f"missing ```json {name}``` block")
    return json.loads(m.group(1))


def read_prereg(path: Path = PREREG_PATH) -> Prereg:
    text = Path(path).read_text(encoding="utf-8")
    sha = _HASH_RE.search(text)
    if not sha:
        raise PreregMismatch("missing thresholds_sha256 line")
    return Prereg(
        thresholds_sha256=sha.group(1),
        thresholds=_block(text, "thresholds"),
        cases=_block(text, "cases"),
    )


def check_frozen(th: Thresholds, path: Path = PREREG_PATH) -> None:
    pre = read_prereg(path)
    if pre.thresholds_sha256 != thresholds_sha256(th) or pre.thresholds != th.model_dump():
        raise PreregMismatch("thresholds differ from eval/PREREG.md; make a new PREREG version")


def main(argv: list[str]) -> int:
    if "--hash" in argv:
        sys.stdout.write(thresholds_sha256(Thresholds()) + "\n")
    elif "--write" in argv:
        PREREG_PATH.write_text(render_prereg(), encoding="utf-8")
    else:
        sys.stderr.write("usage: python -m eval.prereg --hash | --write\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
