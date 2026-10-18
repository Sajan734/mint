"""Supabase._req error handling: python -m pytest supabase_setup"""
import io
import urllib.error

import pytest

from supabase_setup import storage


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def client(monkeypatch, outcomes):
    """A Supabase whose urlopen returns or raises `outcomes` in order; returns (client, calls)."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.setattr(storage.time, "sleep", lambda s: None)
    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        out = outcomes[len(calls) - 1]
        if isinstance(out, BaseException):
            raise out
        return FakeResponse(out)

    monkeypatch.setattr(storage.urllib.request, "urlopen", urlopen)
    return storage.Supabase(), calls


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"body"))


@pytest.mark.parametrize("first", [urllib.error.URLError("reset"), TimeoutError("slow"), http_error(503)])
def test_transient_failure_is_retried_once(monkeypatch, first):
    sb, calls = client(monkeypatch, [first, b"ok"])
    assert sb.download("assets", "a.json") == b"ok"
    assert len(calls) == 2


@pytest.mark.parametrize("err", [urllib.error.URLError("down"), TimeoutError("slow"), http_error(502)])
def test_repeated_failure_is_a_runtime_error(monkeypatch, err):
    sb, calls = client(monkeypatch, [err, err])
    with pytest.raises(RuntimeError):
        sb.download("assets", "a.json")
    assert len(calls) == 2


def test_client_error_is_not_retried(monkeypatch):
    sb, calls = client(monkeypatch, [http_error(404)])
    with pytest.raises(RuntimeError, match="404"):
        sb.download("assets", "missing.json")
    assert len(calls) == 1
