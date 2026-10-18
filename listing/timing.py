"""Per-run stage timing, saved to runs/<item>/timings.json so any run can be checked later.

run_pipeline starts a RunTimer; run_stage opens a stage on it. Inside a stage, span(kind) marks time spent waiting on
something outside our code (gemini, jev, serper, download, upload). Spans of one kind that overlap (12 Jev requests
at once) count as the time they cover together, not their sum, so each stage splits into wall = the union of its
external spans + own (our code). note() attaches extra facts to a stage.

The timer lives in a ContextVar: each run (and each stage task inside it) sees its own, and nothing is shared between
runs. Outside a run, span() and note() do nothing, so stages and scripts work the same without a timer.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

EXTERNAL_KINDS = ("gemini", "jev", "serper", "download", "upload")


@dataclass
class StageTiming:
    key: str  # the stage name, with "#2" etc. when a stage runs twice (finalize)
    start: float  # seconds since the run started
    after: tuple[str, ...] = ()  # the stage keys it waited for, for the critical path
    end: float | None = None
    cache_hit: bool = False
    spans: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunTimer:
    t0: float = field(default_factory=time.perf_counter)
    stages: dict[str, StageTiming] = field(default_factory=dict)
    milestones: dict[str, float] = field(default_factory=dict)  # seconds since the run started

    def now(self) -> float:
        return time.perf_counter() - self.t0


_RUN: ContextVar[RunTimer | None] = ContextVar("listing_run_timer", default=None)
_STAGE: ContextVar[StageTiming | None] = ContextVar("listing_stage_timing", default=None)


def start_run() -> RunTimer:
    timer = RunTimer()
    _RUN.set(timer)
    return timer


def current_run() -> RunTimer | None:
    return _RUN.get()


@contextmanager
def stage(name: str, after: tuple[str, ...] | list[str] = ()) -> Iterator[StageTiming | None]:
    """Times one stage of the current run. Yields None outside a run."""
    run = _RUN.get()
    if run is None:
        yield None
        return
    key, n = name, 1
    while key in run.stages:
        n += 1
        key = f"{name}#{n}"
    timing = StageTiming(key=key, start=run.now(), after=tuple(after))
    run.stages[key] = timing
    token = _STAGE.set(timing)
    try:
        yield timing
    finally:
        timing.end = run.now()
        _STAGE.reset(token)


@contextmanager
def span(kind: str) -> Iterator[None]:
    """Marks time inside the current stage spent waiting on `kind` (one of EXTERNAL_KINDS)."""
    run, current = _RUN.get(), _STAGE.get()
    if run is None or current is None:
        yield
        return
    start = run.now()
    try:
        yield
    finally:
        current.spans.setdefault(kind, []).append((start, run.now()))


def note(key: str, value: Any) -> None:
    """Attaches a fact to the current stage (a list when the same key is noted again)."""
    current = _STAGE.get()
    if current is None:
        return
    if key in current.notes:
        previous = current.notes[key]
        current.notes[key] = [*previous, value] if isinstance(previous, list) else [previous, value]
    else:
        current.notes[key] = value


def milestone(name: str) -> None:
    run = _RUN.get()
    if run is not None:
        run.milestones.setdefault(name, run.now())


# --- report (pure) ----------------------------------------------------------------------------


def union_seconds(intervals: list[tuple[float, float]]) -> float:
    """How long the intervals cover together."""
    total, reach = 0.0, None
    for start, end in sorted(intervals):
        if reach is None or start > reach:
            total += end - start
            reach = end
        elif end > reach:
            total += end - reach
            reach = end
    return total


def critical_path(stages: dict[str, StageTiming], last: str) -> list[str]:
    """The chain of stages that decided when `last` finished: from `last`, step to whichever stage it waited for
    finished latest, until a stage waited for nothing."""
    path, key = [], last
    while key in stages:
        path.append(key)
        waited = [stages[k] for k in stages[key].after if k in stages and stages[k].end is not None]
        if not waited:
            break
        key = max(waited, key=lambda s: s.end).key
    return path[::-1]


def ms(seconds: float | None) -> int | None:
    return None if seconds is None else round(seconds * 1000)


def stage_report(s: StageTiming) -> dict[str, Any]:
    end = s.end if s.end is not None else s.start
    external = {kind: ms(union_seconds(iv)) for kind, iv in s.spans.items()}
    waiting = union_seconds([i for iv in s.spans.values() for i in iv])
    entry = {"start_ms": ms(s.start), "end_ms": ms(end), "wall_ms": ms(end - s.start), "cache_hit": s.cache_hit,
             "external_ms": external, "own_ms": max(ms(end - s.start - waiting), 0), "after": list(s.after)}
    if s.notes:
        entry["notes"] = s.notes
    return entry


def report(run: RunTimer, ends: dict[str, str]) -> dict[str, Any]:
    """ends: milestone name -> the stage key that completed it (e.g. result_json -> finalize)."""
    stages = {k: stage_report(s) for k, s in run.stages.items()}
    out: dict[str, Any] = {"stages": stages, "milestones_ms": {k: ms(v) for k, v in run.milestones.items()},
                           "critical_path": {}, "critical_path_breakdown_ms": {}}
    for name, last in ends.items():
        path = critical_path(run.stages, last)
        out["critical_path"][name] = [{"stage": k, "wall_ms": stages[k]["wall_ms"], "end_ms": stages[k]["end_ms"]}
                                      for k in path]
        breakdown: dict[str, int] = {"own": 0}
        for k in path:  # the stages on a path run one after another, so their times add up
            breakdown["own"] += stages[k]["own_ms"]
            for kind, value in stages[k]["external_ms"].items():
                breakdown[kind] = breakdown.get(kind, 0) + value
        out["critical_path_breakdown_ms"][name] = breakdown
    return out


def write(run: RunTimer, path: Path, ends: dict[str, str], extra: dict[str, Any] | None = None) -> None:
    data = report(run, ends) | (extra or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
