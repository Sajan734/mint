from pathlib import Path

import httpx
import pytest
from groq import APITimeoutError, BadRequestError, InternalServerError, RateLimitError
from pydantic import SecretStr

from buyer_agent.config import Settings
from buyer_agent.errors import AgentError
from buyer_agent.groq_client import (
    GroqAnswer,
    GroqCallError,
    LiveGroq,
    ReplayGroq,
    classify_groq_error,
    save_recording,
)
from tests.fakes_groq import FakeGroq
from tests.fakes_jev import run_sync

_REQ = httpx.Request("POST", "https://x.invalid")


def _status(cls, code):
    return cls("m", response=httpx.Response(code, request=_REQ), body=None)


def test_live_constructor_timeout_12_no_sdk_retries(tmp_path):
    s = Settings(
        typesafe_api_key=SecretStr("k"),
        groq_api_key=SecretStr("g"),
        buyer_agent_token=SecretStr("t"),
        data_root=tmp_path,
        runs_root=tmp_path,
    )
    client = LiveGroq(s)._client
    assert client.timeout == 12.0 and client.max_retries == 0


def test_replay_by_key(tmp_path: Path):
    save_recording(tmp_path, "d1", GroqAnswer("llama-3.3-70b-versatile", '{"summary":"x"}'))
    got = run_sync(ReplayGroq(tmp_path).chat("m", "s", "u", key="d1"))
    assert got.text == '{"summary":"x"}'
    with pytest.raises(AgentError):
        run_sync(ReplayGroq(tmp_path).chat("m", "s", "u", key="missing"))


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (_status(RateLimitError, 429), True),
        (_status(InternalServerError, 503), True),
        (APITimeoutError(_REQ), True),
        (_status(BadRequestError, 400), False),
    ],
)
def test_error_classification_429_5xx_timeout_vs_400(exc, retryable):
    assert classify_groq_error(exc).retryable is retryable


def test_fake_groq_scripts_errors():
    f = FakeGroq([GroqCallError(True), GroqAnswer("m", "{}")])
    with pytest.raises(GroqCallError):
        run_sync(f.chat("m", "s", "u"))
    assert (run_sync(f.chat("m", "s", "u"))).text == "{}"
