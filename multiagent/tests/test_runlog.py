import json
import logging
from uuid import uuid4

import pytest

from buyer_agent import runlog
from buyer_agent.errors import AgentError
from buyer_agent.models import CompareRequest, SplatRef
from buyer_agent.runlog import REDACTED, RedactingFilter, RunLog, redact, safe_exc


def test_redact_strips_key_token_authorization_fields_nested():
    obj = {"api_key": "a", "x": [{"Authorization": "b", "ok": 1}], "n": {"my_token": "c"}}
    assert redact(obj) == {
        "api_key": REDACTED,
        "x": [{"Authorization": REDACTED, "ok": 1}],
        "n": {"my_token": REDACTED},
    }


def test_redact_strips_gsk_and_typesafe_prefixed_strings():
    s = redact({"m": "failed with gsk_abcdef123456 and typesafe_ABCDEFGH12 ok"})
    assert "gsk_" not in s["m"] and "typesafe_" not in s["m"] and "failed with" in s["m"]


def test_redact_strips_registered_secret_values(monkeypatch):
    monkeypatch.setattr(runlog, "_known_secrets", set())
    runlog.register_secrets("hunter2-secret-value")
    assert redact("boom hunter2-secret-value!") == f"boom {REDACTED}!"


def test_atomic_write_leaves_no_partial_file_on_error(tmp_path):
    log = RunLog(tmp_path, str(uuid4()))
    with pytest.raises(TypeError):
        log.save_json("a.json", {"x": object()})
    assert not list(log.dir.rglob("*")) or all(p.is_dir() for p in log.dir.rglob("*"))


def test_run_id_must_be_uuid_no_traversal(tmp_path):
    for bad in ("../x", "abc", ""):
        with pytest.raises(AgentError):
            RunLog(tmp_path, bad)
    log = RunLog(tmp_path, str(uuid4()))
    with pytest.raises(AgentError):
        log.save_png("../../evil.png", b"x")


def test_logging_filter_redacts_message_args():
    rec = logging.LogRecord("n", logging.INFO, "p", 1, "key %s", ("gsk_abcdef123456",), None)
    assert RedactingFilter().filter(rec) and "gsk_" not in rec.getMessage()


def test_attempt_excluded_from_hash():
    base = {
        "comparison_id": uuid4(),
        "listing_id": "L1",
        "listing_splat": SplatRef(path="a.ply", format="ply"),
        "buyer_splat": SplatRef(path="b.ply", format="ply"),
    }
    a, b = CompareRequest(**base, attempt=1), CompareRequest(**base, attempt=3)
    assert RunLog.request_hash(a) == RunLog.request_hash(b)
    c = CompareRequest(**{**base, "listing_id": "L2"})
    assert RunLog.request_hash(a) != RunLog.request_hash(c)


def test_exception_strings_redacted_by_default():
    assert "gsk_" not in safe_exc(RuntimeError("bad gsk_abcdef123456"))
    assert safe_exc(ValueError("x")).startswith("ValueError: ")


def test_failed_response_not_persisted(tmp_path):
    log = RunLog(tmp_path, str(uuid4()))
    assert log.save_json("response.json", {"status": "failed"}) is None
    assert log.load_response() is None
    p = log.save_json("jev/view_00.json", {"status": "failed", "token": "t"})
    assert json.loads(p.read_text())["token"] == REDACTED
    assert log.save_failure_detail("left/90", "oops").name == "failure_left_90.json"
