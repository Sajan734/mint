"""timing: interval unions, the critical path, and stage/span recording. Pure, no APIs."""

import asyncio
import json

import pytest

import timing
from timing import StageTiming, critical_path, union_seconds


@pytest.mark.parametrize(
    "intervals, total",
    [
        ([], 0.0),
        ([(0.0, 1.0)], 1.0),
        ([(0.0, 1.0), (0.5, 2.0)], 2.0),  # overlapping: 12 Jev requests at once count once
        ([(0.0, 1.0), (2.0, 3.0)], 2.0),  # apart: they add
        ([(1.0, 2.0), (0.0, 3.0)], 3.0),  # one inside another
        ([(2.0, 3.0), (0.0, 1.0), (0.5, 1.5)], 2.5),  # unsorted
    ],
)
def test_union_seconds(intervals, total):
    assert union_seconds(intervals) == pytest.approx(total)


def stages(**spec):
    """name=(start, end, after...)"""
    return {k: StageTiming(key=k, start=v[0], end=v[1], after=tuple(v[2:])) for k, v in spec.items()}


def test_critical_path_follows_the_latest_input():
    s = stages(render=(0, 20), identify=(20, 24, "render"), baseline=(24, 26, "identify"),
               match=(26, 27, "baseline"), text=(24, 26, "identify"), price=(24, 30, "identify"),
               finalize=(30, 30.1, "match", "text", "price"))
    assert critical_path(s, "finalize") == ["render", "identify", "price", "finalize"]


def test_critical_path_skips_inputs_that_never_ran():
    s = stages(a=(0, 1), b=(1, 2, "a", "missing"))
    assert critical_path(s, "b") == ["a", "b"]


def test_spans_and_notes_do_nothing_outside_a_run():
    with timing.span("gemini"):
        pass
    timing.note("x", 1)
    timing.milestone("result_json")  # no error, nothing recorded


def test_stage_records_wall_external_and_own(tmp_path):
    async def run():
        timer = timing.start_run()
        with timing.stage("render"):
            with timing.span("modal"):
                await asyncio.sleep(0.02)
            timing.note("modal_render_splat", {"cold": True})
        with timing.stage("match_gate", after=("render",)):
            async def jev():
                with timing.span("jev"):
                    await asyncio.sleep(0.02)
            await asyncio.gather(jev(), jev(), jev())  # concurrent: about 20 ms of jev, not 60
        with timing.stage("finalize", after=("match_gate",)):
            pass
        with timing.stage("finalize", after=("finalize",)):  # a stage that runs twice gets "#2"
            pass
        timing.milestone("result_json")
        timing.write(timer, tmp_path / "timings.json", {"result_json": "finalize#2"})

    asyncio.run(run())
    data = json.loads((tmp_path / "timings.json").read_text())
    gate = data["stages"]["match_gate"]
    assert 15 <= gate["external_ms"]["jev"] < 50 and gate["own_ms"] < gate["wall_ms"]
    assert data["stages"]["render"]["notes"]["modal_render_splat"] == {"cold": True}
    assert [p["stage"] for p in data["critical_path"]["result_json"]] == ["render", "match_gate", "finalize",
                                                                          "finalize#2"]
    assert set(data["critical_path_breakdown_ms"]["result_json"]) == {"own", "modal", "jev"}
    assert "result_json" in data["milestones_ms"]
