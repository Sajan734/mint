"""Eval harness (U28). `python -m eval.run_eval --split tune|heldout [--out report.json]`.

Runs each pre-registered case RUNS times through buyer_agent.pipeline.compare and reports n, the
runs and their spread, Wilson 95%, the false-`same` rate on changed cases, per-class counts, the
cases-file hash and the PREREG commit, and the caveats. Thresholds are never tuned here: the run
refuses if they differ from eval/PREREG.md. Clients are injectable, so tests run offline.

Case shape (PREREG `cases` block): case, split, scene, mode ("views" | "splats"), manifest,
claims (null | inline object | path under DATA_ROOT), expected_label, acceptable, wrong,
and for mode "splats" also listing_splat + buyer_splat (SplatRef objects).
"""

import asyncio
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from buyer_agent.aggregate import Thresholds
from buyer_agent.config import JEV_MODEL_PIN, Settings
from buyer_agent.groq_client import GroqClient
from buyer_agent.jev_client import JevClient
from buyer_agent.models import CompareRequest, ListingClaims
from buyer_agent.pipeline import Deps, compare
from buyer_agent.runlog import RunLog
from eval.prereg import PREREG_PATH, PreregMismatch, check_frozen, read_prereg
from eval.stats import class_counts, false_same, spread, wilson

EXPECTED_PATH = Path(__file__).resolve().parent / "expected.json"
RUNS = 3
CAVEATS = (
    "PASLCD pairs are photos, not renders (BD5); CONTEXT_V2 says renders.",
    "The CPU renderer is unvalidated (AM-26) until the shift check passes.",
    "Smoke test, not accuracy (AM-22): small n, no accuracy claim.",
)


class EvalError(RuntimeError):
    """Refusal to run or report; the message says what to fix."""


@dataclass(frozen=True)
class RunResult:
    run: int
    label: str  # verdict label, or "failed"
    outcome: str  # "ok" | "wrong" | "other"
    model: str
    evidence_score: float | None


def load_cases(
    split: str, prereg_path: Path = PREREG_PATH, expected_path: Path = EXPECTED_PATH
) -> tuple[list[dict[str, Any]], str]:
    """Cases for one split, plus the sha256 of expected.json. Never invents cases."""
    try:
        cases = read_prereg(prereg_path).cases
    except (PreregMismatch, OSError, ValueError) as exc:
        raise EvalError(f"cannot read PREREG cases: {exc}") from exc
    if not cases:
        raise EvalError("PREREG cases block is empty; U32 fills it before any eval run")
    if not expected_path.is_file():
        raise EvalError(f"missing {expected_path.name}; U32 writes it with the PREREG cases")
    raw = expected_path.read_bytes()
    expected = json.loads(raw)
    by_case = {e["case"]: e for e in expected} if isinstance(expected, list) else dict(expected)
    for c in cases:
        e = by_case.get(c["case"])
        if e is None or e.get("expected_label") != c["expected_label"]:
            raise EvalError(f"expected.json disagrees with PREREG for case {c['case']!r}")
    picked = [c for c in cases if c["split"] == split]
    if not picked:
        raise EvalError(f"no pre-registered cases in split {split!r}")
    return picked, hashlib.sha256(raw).hexdigest()


def prereg_commit(path: Path = PREREG_PATH) -> str:
    """Last commit touching PREREG.md, or a loud marker when it is not committed (AM-24)."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", path.name],
            cwd=path.parent,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or "UNCOMMITTED"


def build_request(case: dict[str, Any], run: int, data_root: Path) -> CompareRequest:
    claims = case.get("claims")
    if isinstance(claims, str):
        claims = json.loads((data_root / claims).read_text(encoding="utf-8"))
    body: dict[str, Any] = {
        "comparison_id": str(uuid5(NAMESPACE_URL, f"eval/{case['case']}/run{run}")),
        "listing_id": case["case"][:64],
        "claims": ListingClaims.model_validate(claims) if claims else None,
    }
    if case["mode"] == "views":
        body["view_pairs"] = {"manifest_path": case["manifest"]}
    elif case["mode"] == "splats":
        body["listing_splat"], body["buyer_splat"] = case["listing_splat"], case["buyer_splat"]
    else:
        raise EvalError(f"case {case['case']!r}: unknown mode {case['mode']!r}")
    return CompareRequest(**body)


def classify(case: dict[str, Any], label: str) -> str:
    if label in case["wrong"]:
        return "wrong"
    return "ok" if label in case["acceptable"] else "other"


async def run_once(case: dict[str, Any], run: int, deps: Deps) -> RunResult:
    resp = await compare(build_request(case, run, deps.settings.data_root), deps)
    label = resp.verdict.label if resp.verdict else "failed"
    score = resp.verdict.evidence_score if resp.verdict else None
    return RunResult(run, label, classify(case, label), resp.model_ids.get("jev", ""), score)


def summarise(cases: list[dict[str, Any]], runs: list[list[RunResult]]) -> dict[str, Any]:
    """runs[i] = the RUNS results for cases[i]. Pure; tested without any client."""
    n_runs = len(runs[0]) if runs else 0
    per_run: list[dict[str, Any]] = []
    for r in range(n_runs):
        got = [runs[i][r].label for i in range(len(cases))]
        fs_k, fs_n = false_same([c["expected_label"] for c in cases], got)
        wrong = sum(runs[i][r].outcome == "wrong" for i in range(len(cases)))
        per_run.append(
            {
                "run": r + 1,
                "wrong": wrong,
                "false_same": fs_k,
                "changed": fs_n,
                "counts": class_counts(got),
            }
        )
    wrong_n = sum(p["wrong"] for p in per_run)
    k, n = sum(p["false_same"] for p in per_run), sum(p["changed"] for p in per_run)
    n_ok = sum(x.outcome == "ok" for row in runs for x in row)
    total = n_runs * len(cases)
    fs_rates = [p["false_same"] / p["changed"] for p in per_run if p["changed"]]
    models = sorted({x.model for row in runs for x in row if x.model})
    return {
        "n_cases": len(cases),
        "n_runs": n_runs,
        "per_run": per_run,
        "exact_or_acceptable": {"k": n_ok, "n": total, "wilson95": wilson(n_ok, total)},
        "false_same_on_changed": {
            "k": k,
            "n": n,
            "wilson95": wilson(k, n),
            "per_run_spread": spread(fs_rates),
        },
        "class_counts": class_counts([x.label for row in runs for x in row]),
        "s2_pass": wrong_n == 0 and total > 0,
        "models": models,
        "model_pin_ok": models == [JEV_MODEL_PIN],
    }


async def run_eval(
    split: str,
    settings: Settings,
    jev: JevClient,
    groq: GroqClient,
    renderer: Any = None,
    *,
    prereg_path: Path = PREREG_PATH,
    expected_path: Path = EXPECTED_PATH,
    commit_of: Callable[[Path], str] = prereg_commit,
    resolver: Callable[..., Any] | None = None,
    n_runs: int = RUNS,
) -> dict[str, Any]:
    check_frozen(Thresholds(), prereg_path)  # raises PreregMismatch: never tune here
    cases, cases_sha = load_cases(split, prereg_path, expected_path)
    extra = {"resolver": resolver} if resolver else {}
    deps = Deps(
        settings=settings,
        jev=jev,
        groq=groq,
        renderer=renderer,
        runlog_factory=lambda rid: RunLog(settings.runs_root, rid),
        **extra,
    )
    runs = [[await run_once(c, r, deps) for r in range(1, n_runs + 1)] for c in cases]
    report = summarise(cases, runs)
    report.update(
        split=split,
        cases_sha256=cases_sha,
        prereg_commit=commit_of(prereg_path),
        thresholds_note="frozen per eval/PREREG.md; none tuned by this harness",
        caveats=list(CAVEATS),
        results={c["case"]: [asdict(x) for x in row] for c, row in zip(cases, runs, strict=True)},
    )
    if not report["model_pin_ok"]:
        report["caveats"].append(f"MODEL PIN MISMATCH: saw {report['models']}, pin {JEV_MODEL_PIN}")
    return report


def main(argv: list[str]) -> int:
    import argparse

    from buyer_agent.api import _default_clients
    from buyer_agent.config import load_settings
    from buyer_agent.render import CpuPointRenderer

    ap = argparse.ArgumentParser(prog="eval.run_eval")
    ap.add_argument("--split", choices=("tune", "heldout"), required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    settings = load_settings()
    jev, groq = _default_clients(settings)  # live only when BUYER_AGENT_LIVE=1
    try:
        report = asyncio.run(
            run_eval(args.split, settings, jev, groq, CpuPointRenderer(settings.render_max_points))
        )
    except (EvalError, PreregMismatch) as exc:
        sys.stderr.write(f"eval refused: {exc}\n")
        return 2
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
