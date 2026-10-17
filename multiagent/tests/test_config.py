import importlib

import pytest

from buyer_agent import config
from buyer_agent.errors import AgentError

KEYS = ("TYPESAFE_API_KEY", "GROQ_API_KEY", "BUYER_AGENT_TOKEN", "DATA_ROOT")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Full valid env; env_file points at a missing file so the real .env is never read."""
    for k in ("BUYER_AGENT_LIVE", "BUYER_AGENT_RENDERER_VALIDATED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-secret-1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_2")
    monkeypatch.setenv("BUYER_AGENT_TOKEN", "tok-secret-3-" + "x" * 24)
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    return tmp_path / "missing.env"


@pytest.mark.parametrize("name", KEYS)
def test_missing_key_raises_clear_message_naming_variable(env, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(AgentError) as e:
        config.load_settings(env)
    assert name in e.value.detail


def test_short_token_rejected_with_clear_error(env, monkeypatch):
    monkeypatch.setenv("BUYER_AGENT_TOKEN", "short-token")
    with pytest.raises(AgentError) as e:
        config.load_settings(env)
    assert "at least 32" in e.value.detail


def test_secrets_not_in_repr_or_dump(env):
    s = config.load_settings(env)
    text = repr(s) + str(s)
    assert not any(x in text for x in ("ts-secret-1", "gsk_secret_2", "tok-secret-3-" + "x" * 24))
    assert s.groq_api_key.get_secret_value() == "gsk_secret_2"


def test_no_dotenv_on_import(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("load_dotenv called at import")

    monkeypatch.setattr("dotenv.load_dotenv", boom)
    importlib.reload(config)
    monkeypatch.undo()
    importlib.reload(config)


def test_data_root_must_exist(env, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "nope"))
    with pytest.raises(AgentError):
        config.load_settings(env)


def test_relative_data_root_resolves_against_repo_root(env, monkeypatch, tmp_path):
    (tmp_path / "multiagent" / "data").mkdir(parents=True)
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("DATA_ROOT", "multiagent/data")
    assert config.load_settings(env).data_root == (tmp_path / "multiagent" / "data").resolve()


def test_amended_defaults(env):
    s = config.load_settings(env)
    assert (
        s.groq_timeout_s, s.groq_max_retries, s.advise_cap_s, s.paid_calls_per_hour,
        s.attempts_per_id, s.max_body_bytes, s.run_retention_days, s.claims_max_side,
        s.renderer_validated, s.live, s.jev_model,
    ) == (12, 0, 30, 400, 3, 65536, 14, 768, False, False, "jev-1.13.0")  # fmt: skip
    assert s.runs_root == config.PACKAGE_ROOT / "runs"


def test_flags_from_env(env, monkeypatch):
    monkeypatch.setenv("BUYER_AGENT_LIVE", "1")
    monkeypatch.setenv("BUYER_AGENT_RENDERER_VALIDATED", "true")
    s = config.load_settings(env)
    assert s.live and s.renderer_validated
