import json
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr
from typesafe_sdk import TypeSafeAPIError, TypeSafeAPITimeoutError

from buyer_agent.config import JEV_MODEL_PIN, Settings
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.jev_client import JevAnswer, LiveJev, ReplayJev, map_jev_error, save_recording
from tests.fakes_jev import FakeJev, answer, run_sync


def _api_error(status: int):
    return TypeSafeAPIError(status, {"error": "x"}, httpx2.Headers())


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (_api_error(401), ErrorCode.JEV_AUTH),
        (_api_error(403), ErrorCode.JEV_AUTH),
        (_api_error(429), ErrorCode.JEV_RATE_LIMITED),
        (TimeoutError(), ErrorCode.JEV_TIMEOUT),
        (_api_error(400), ErrorCode.IMAGE_INVALID),
        (_api_error(503), ErrorCode.JEV_UNAVAILABLE),
        (RuntimeError("boom"), ErrorCode.JEV_UNAVAILABLE),
    ],
)
def test_error_mapping_table(exc, code):
    assert map_jev_error(exc).code is code


def test_sdk_timeout_class_maps_to_timeout():
    exc = TypeSafeAPITimeoutError.__new__(TypeSafeAPITimeoutError)
    assert map_jev_error(exc).code is ErrorCode.JEV_TIMEOUT


def test_replay_returns_recorded_answer_by_key(tmp_path: Path):
    save_recording(tmp_path, "v1", answer(shape_diff=0.7))
    got = run_sync(ReplayJev(tmp_path).ask({}, {}, key="v1"))
    assert got.nouls == {"shape_diff": 0.7} and got.model == JEV_MODEL_PIN


def test_replay_missing_key_raises_clear_error(tmp_path: Path):
    with pytest.raises(AgentError) as e:
        run_sync(ReplayJev(tmp_path).ask({}, {}, key="nope"))
    assert "nope" in e.value.detail


def test_replay_refuses_recording_with_other_model(tmp_path: Path):
    save_recording(tmp_path, "v1", JevAnswer(model="jev-1.14.0", nouls={"a": 0.1}))
    with pytest.raises(AgentError) as e:
        run_sync(ReplayJev(tmp_path).ask({}, {}, key="v1"))
    assert "jev-1.14.0" in e.value.detail


def test_replay_rejects_path_traversal_key(tmp_path: Path):
    with pytest.raises(AgentError):
        run_sync(ReplayJev(tmp_path).ask({}, {}, key="../x"))


def test_replay_bad_file_is_bad_response(tmp_path: Path):
    (tmp_path / "k.json").write_text(json.dumps({"bogus": 1}))
    with pytest.raises(AgentError) as e:
        run_sync(ReplayJev(tmp_path).ask({}, {}, key="k"))
    assert e.value.code is ErrorCode.JEV_BAD_RESPONSE


def test_fake_jev_scripts_answers_and_errors():
    f = FakeJev([answer(a=0.5), AgentError(ErrorCode.JEV_TIMEOUT)])
    assert (run_sync(f.ask({}, {}, key="k"))).nouls == {"a": 0.5}
    with pytest.raises(AgentError):
        run_sync(f.ask({}, {}))
    assert len(f.calls) == 2


def test_live_constructor_makes_no_network_call(tmp_path):
    s = Settings(
        typesafe_api_key=SecretStr("k"),
        groq_api_key=SecretStr("g"),
        buyer_agent_token=SecretStr("t"),
        data_root=tmp_path,
        runs_root=tmp_path,
    )
    live = LiveJev(s)  # conftest blocks sockets: any connect would raise
    assert live._wait_for == 50
