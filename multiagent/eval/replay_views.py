"""Re-apply `aggregate` (frozen default thresholds) to the raw per-view Jev answers of a run.

    python -m eval.replay_views runs/<id> [runs/<id2> ...]

Reads runs/<id>/jev/view_*.json (+ optional response.json for failures and alignment). No network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from buyer_agent.aggregate import aggregate
from buyer_agent.errors import AgentError
from buyer_agent.jev_client import JevAnswer
from buyer_agent.judge import parse_scores
from buyer_agent.models import AlignmentMetrics, JevViewScores, Verdict, ViewFailure


def out(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def load_scores(run_dir: Path) -> list[JevViewScores]:
    scores = []
    for path in sorted((run_dir / "jev").glob("view_*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        answer = JevAnswer(
            model=raw["model"], nouls=raw["nouls"], latency_ms=raw["latency_ms"],
            timestamp=raw.get("timestamp", ""),
        )  # fmt: skip
        scores.append(parse_scores(raw["view"], answer))
    return scores


def replay(run_dir: Path) -> Verdict:
    scores = load_scores(run_dir)
    failures: list[ViewFailure] = []
    alignment, mode = None, "skipped_view_pairs"
    response = run_dir / "response.json"
    if response.is_file():
        ev = (json.loads(response.read_text(encoding="utf-8")).get("verdict") or {}).get(
            "evidence"
        ) or {}
        failures = [ViewFailure(**f) for f in ev.get("failed_views", [])]
        mode = ev.get("alignment_mode", mode)
        alignment = AlignmentMetrics(**ev["alignment"]) if ev.get("alignment") else None
    requested = max(len(list(run_dir.glob("a_*.png"))), len(scores) + len(failures), 1)
    return aggregate(scores, failures, requested, alignment, mode)


def main(argv: list[str]) -> int:
    if not argv:
        out("usage: python -m eval.replay_views runs/<id> ...")
        return 1
    for arg in argv:
        run_dir = Path(arg)
        try:
            v = replay(run_dir)
        except (AgentError, OSError, ValueError, KeyError) as exc:
            out(f"{run_dir.name}: cannot replay ({type(exc).__name__})")
            continue
        score = "-" if v.evidence_score is None else f"{v.evidence_score:.3f}"
        e = v.evidence
        out(
            f"{run_dir.name}: {v.label} score={score} usable={e.usable_views}/{e.answered_views} "
            f"flagged={','.join(e.flagged) or '-'} | {v.reason}"
        )
        for cat, c in e.categories.items():
            out(f"  {cat}: evidence={c.evidence:.2f} max={c.max:.2f} views={','.join(c.views)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
