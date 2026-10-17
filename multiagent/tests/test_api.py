import asyncio
import os
import socket
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from buyer_agent.api import create_app
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.groq_client import GroqCallError
from tests.fakes_jev import answer
from tests.test_judge import GOOD, REAL_CONNECT, settings
from tests.test_sources import write_manifest

TOKEN = "tok-abcdefgh12345"
SECRET = "gsk_TOPSECRETVALUE123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
LEAK = "detail-that-must-not-leak"


@pytest.fixture(autouse=True)
def _loopback(monkeypatch):
    # TestClient needs a loopback socketpair; the conftest guard blocks connect().
    monkeypatch.setattr(socket.socket, "connect", REAL_CONNECT)


class Jev:
    def __init__(self, fail=False, gate=None):
        self.calls, self.fail, self.gate = 0, fail, gate

    async def ask(self, state, questions, *, key=""):
        self.calls += 1
        while self.gate is not None and not self.gate.is_set():
            await asyncio.sleep(0.01)
        if self.fail:
            raise AgentError(ErrorCode.JEV_TIMEOUT, LEAK)
        return answer(**GOOD)


class Groq:
    async def chat(self, model, system, user, *, key=""):
        raise GroqCallError(False, "down")


@pytest.fixture
def env(tmp_path):
    write_manifest(tmp_path)
    return tmp_path


def make(env, jev=None, **kw):
    st = settings(
        data_root=env,
        runs_root=env / "runs",
        buyer_agent_token=SecretStr(TOKEN),
        typesafe_api_key=SecretStr(SECRET),
        **kw,
    )
    return create_app(st, jev=jev or Jev(), groq=Groq())


def body(cid=None, **kw):
    base = {
        "comparison_id": cid or str(uuid4()),
        "listing_id": "x",
        "view_pairs": {"manifest_path": "m.json"},
    }
    return {**base, **kw}


def post(c, b, headers=AUTH):
    return c.post("/v1/comparisons", json=b, headers=headers)


def test_healthz_no_auth_no_calls(env):
    jev = Jev()
    r = TestClient(make(env, jev)).get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True} and jev.calls == 0


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer nope"},
        {"Authorization": TOKEN},
        {"Authorization": b"Bearer \xc3\xbc"},
    ],
)
def test_401_missing_and_wrong_token(env, headers):
    r = post(TestClient(make(env)), body(), headers)
    assert r.status_code == 401 and TOKEN not in r.text


def test_happy_path_200(env):
    r = post(TestClient(make(env)), body())
    assert r.status_code == 200 and r.json()["status"] == "done"


def test_422_invalid_body_plain_message(env):
    r = post(TestClient(make(env)), {"comparison_id": "not-a-uuid", "evil": "<script>"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INPUT_INVALID"
    assert "script" not in r.text and "pydantic" not in r.text.lower()


def test_traversal_path_422(env):
    b = body(view_pairs={"manifest_path": "../x.json"})
    assert post(TestClient(make(env)), b).status_code == 422


def test_idempotent_replay_same_body_returns_stored_no_jev_call(env):
    jev, b = Jev(), body()
    c = TestClient(make(env, jev))
    first = post(c, b)
    calls = jev.calls
    again = post(c, b)
    assert again.status_code == 200 and again.json() == first.json() and jev.calls == calls


def test_attempt_excluded_from_hash(env):
    jev, cid = Jev(), str(uuid4())
    c = TestClient(make(env, jev))
    post(c, body(cid))
    calls = jev.calls
    assert post(c, body(cid, attempt=2)).status_code == 200 and jev.calls == calls


def test_409_same_id_different_body(env):
    cid = str(uuid4())
    c = TestClient(make(env))
    post(c, body(cid))
    assert post(c, body(cid, listing_id="other")).status_code == 409


def test_failed_not_replayed(env):
    jev, b = Jev(fail=True), body()
    c = TestClient(make(env, jev))
    assert post(c, b).json()["status"] == "failed"
    calls = jev.calls
    post(c, b)
    assert jev.calls > calls
    assert c.get(f"/v1/comparisons/{b['comparison_id']}", headers=AUTH).status_code == 404


def test_attempt_cap_3_per_id(env):
    c, b = TestClient(make(env, Jev(fail=True))), body()
    assert [post(c, b).status_code for _ in range(3)] == [200, 200, 200]
    r = post(c, b)
    assert r.status_code == 429 and r.json()["error"]["code"] == "ATTEMPTS_EXHAUSTED"


def test_get_404_and_200(env):
    c, b = TestClient(make(env)), body()
    assert c.get(f"/v1/comparisons/{b['comparison_id']}", headers=AUTH).status_code == 404
    assert c.get("/v1/comparisons/not-a-uuid", headers=AUTH).status_code == 404
    post(c, b)
    got = c.get(f"/v1/comparisons/{b['comparison_id']}", headers=AUTH)
    assert got.status_code == 200 and got.json()["comparison_id"] == b["comparison_id"]
    assert c.get(f"/v1/comparisons/{b['comparison_id']}").status_code == 401


def test_429_after_10_per_hour(env):
    c = TestClient(make(env, rate_per_hour=2))
    assert [post(c, body()).status_code for _ in range(3)] == [200, 200, 429]


def test_rate_limit_keyed_by_ip(env):
    app = make(env, rate_per_hour=1)
    a, b = TestClient(app, client=("1.1.1.1", 1)), TestClient(app, client=("2.2.2.2", 1))
    assert post(a, body()).status_code == 200
    assert post(a, body()).status_code == 429
    assert post(b, body()).status_code == 200


def test_busy_returns_429(env):
    gate = threading.Event()
    with TestClient(make(env, Jev(gate=gate))) as c:
        first = {}
        t = threading.Thread(target=lambda: first.update(r=post(c, body())))
        t.start()
        time.sleep(0.5)
        busy = post(c, body())
        gate.set()
        t.join(10)
    assert busy.status_code == 429 and busy.json()["error"]["code"] == "BUSY"
    assert first["r"].status_code == 200


def test_budget_exhausted_returns_429(env):
    r = post(TestClient(make(env, paid_calls_per_hour=10)), body())
    assert r.status_code == 429 and r.json()["error"]["code"] == "BUDGET_EXHAUSTED"


def test_auth_failures_logged_and_rate_limited(env, caplog):
    c = TestClient(make(env, auth_fail_per_10min=3))
    bad = {"Authorization": "Bearer wrong"}
    with caplog.at_level("WARNING", logger="buyer_agent.api"):
        assert [post(c, body(), bad).status_code for _ in range(3)] == [401, 401, 401]
        assert post(c, body(), bad).status_code == 429
    assert "auth failure" in caplog.text and "wrong" not in caplog.text
    assert post(c, body()).status_code == 429  # locked out even with the right token


def test_content_length_cap(env):
    c = TestClient(make(env))
    assert post(c, body(listing_id="x" * 70_000)).status_code == 413
    chunked = c.post("/v1/comparisons", content=iter([b"{}"]), headers=AUTH)
    assert chunked.status_code == 413


def test_docs_disabled(env):
    c = TestClient(make(env))
    assert [c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")] == [404] * 3


def test_no_cors_headers(env):
    r = TestClient(make(env)).get("/healthz", headers={"Origin": "https://evil.example"})
    assert not any(h.lower().startswith("access-control") for h in r.headers)


def test_detail_stripped_and_no_key_in_error_responses(env):
    c = TestClient(make(env, Jev(fail=True)))
    outs = [
        post(c, body()),
        post(c, body(), {}),
        post(c, {"x": 1}),
        c.get("/v1/comparisons/zzz", headers=AUTH),
    ]
    for r in outs:
        assert LEAK not in r.text and "detail" not in r.text.lower()
        assert SECRET not in r.text and TOKEN not in r.text


def test_startup_prunes_old_runs(env):
    old = env / "runs" / str(uuid4())
    old.mkdir(parents=True)
    (old / "response.json").write_text("{}")
    past = time.time() - 40 * 86400
    os.utime(old / "response.json", (past, past))
    os.utime(old, (past, past))
    with TestClient(make(env)):
        pass
    assert not old.exists()
