import asyncio
import io
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from pydantic import SecretStr

from buyer_agent.config import Settings
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.judge import judge_views
from buyer_agent.models import ViewPair
from tests.fakes_jev import FakeJev, answer

REAL_CONNECT = socket.socket.connect  # captured before the conftest guard patches it


def run(coro):
    """Real event loop for tests of concurrent code. Loopback socketpair only; no network."""
    saved = socket.socket.connect
    socket.socket.connect = REAL_CONNECT
    try:
        return asyncio.run(coro)
    finally:
        socket.socket.connect = saved


def png(size=300, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


def settings(**kw) -> Settings:
    base = Settings(SecretStr("a"), SecretStr("b"), SecretStr("c"), Path("."), Path("."))
    return replace(base, **kw)


def pair(label, a=None, b=None) -> ViewPair:
    return ViewPair(label=label, png_a=a or png(), png_b=b or png())


GOOD = {
    "viewpoint_match": 0.9, "scan_quality_ok": 0.9, "shape_diff": 0.1,
    "part_diff": 0.1, "color_diff": 0.1, "any_diff": 0.1,
}  # fmt: skip


def go(client, pairs, st=None):
    raws, fails = [], []
    out = run(
        judge_views(
            client, pairs, st or settings(),
            lambda label, a: raws.append((label, a)),
            lambda label, code, detail: fails.append((label, code, detail)),
        )
    )  # fmt: skip
    return out, raws, fails


def test_all_views_scored_and_raw_passed_to_runlog():
    jev = FakeJev([answer(**GOOD) for _ in range(3)])
    ((scores, failures), raws, fails) = go(jev, [pair("a"), pair("b"), pair("c")])
    assert [s.view for s in scores] == ["a", "b", "c"]
    assert failures == [] and fails == []
    assert len(raws) == 3 and len(jev.calls) == 3
    assert {c[2] for c in jev.calls} == {"view-00", "view-01", "view-02"}


def test_one_timeout_becomes_view_failure_others_kept():
    jev = FakeJev([answer(**GOOD), TimeoutError("slow secret detail"), answer(**GOOD)])
    ((scores, failures), _, fails) = go(jev, [pair("a"), pair("b"), pair("c")])
    assert len(scores) == 2
    assert [(f.view, f.code) for f in failures] == [("b", "JEV_TIMEOUT")]
    assert fails[0][0] == "b" and fails[0][1] == "JEV_TIMEOUT"


def test_failure_detail_goes_to_runlog_not_model():
    jev = FakeJev([AgentError(ErrorCode.JEV_BAD_RESPONSE, "secret-detail")] + [answer(**GOOD)] * 1)
    ((_, failures), _, fails) = go(jev, [pair("a"), pair("b")])
    assert "secret-detail" not in failures[0].model_dump_json()
    assert fails[0][2] == "secret-detail"


def test_auth_error_cancels_and_raises():
    jev = FakeJev([AgentError(ErrorCode.JEV_AUTH, "401")] * 4)
    with pytest.raises(AgentError) as e:
        go(jev, [pair("a"), pair("b")])
    assert e.value.code is ErrorCode.JEV_AUTH


def test_malformed_answer_becomes_bad_response():
    jev = FakeJev([answer(viewpoint_match=0.9), answer(**GOOD)])
    ((scores, failures), _, _) = go(jev, [pair("a"), pair("b")])
    assert [f.code for f in failures] == ["JEV_BAD_RESPONSE"] and len(scores) == 1


def test_image_invalid_is_view_failure_no_call():
    jev = FakeJev([answer(**GOOD)])
    ((scores, failures), _, _) = go(jev, [pair("bad", a=b"not a png"), pair("ok")])
    assert [f.code for f in failures] == ["IMAGE_INVALID"] and len(scores) == 1
    assert len(jev.calls) == 1


def test_duplicate_labels_rejected():
    with pytest.raises(AgentError) as e:
        go(FakeJev([]), [pair("a"), pair("a")])
    assert e.value.code is ErrorCode.INPUT_INVALID


def test_never_more_than_4_in_flight():
    state = {"now": 0, "peak": 0}

    class Slow:
        async def ask(self, state_, questions, *, key=""):
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1
            return answer(**GOOD)

    ((scores, _), _, _) = go(Slow(), [pair(f"v{i}") for i in range(9)])
    assert len(scores) == 9 and state["peak"] == 4


def test_stage_cap_turns_pending_views_into_timeouts():
    class Hang:
        async def ask(self, *a, **k):
            await asyncio.sleep(5)

    ((scores, failures), _, _) = go(Hang(), [pair("a")], settings(judge_stage_cap_s=0.05))
    assert scores == [] and [f.code for f in failures] == ["JEV_TIMEOUT"]


def test_outer_cancel_leaves_no_ask_running():
    finished: list[str] = []

    class Slow:
        async def ask(self, state, questions, *, key=""):
            await asyncio.sleep(0.3)
            finished.append(key)
            return answer(**GOOD)

    async def scenario():
        job = judge_views(Slow(), [pair(f"v{i}") for i in range(4)], settings(), lambda *a: None,
                          lambda *a: None)  # fmt: skip
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(job, 0.1)
        await asyncio.sleep(0.5)

    run(scenario())
    assert finished == []
