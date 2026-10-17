"""Settings. Env is read only inside load_settings(); nothing happens at import."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic import SecretStr

from buyer_agent.errors import AgentError, ErrorCode

JEV_MODEL_PIN = "jev-1.13.0"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # .../multiagent
REPO_ROOT = PACKAGE_ROOT.parent
DEFAULT_ENV_FILE = PACKAGE_ROOT / ".env"
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    typesafe_api_key: SecretStr
    groq_api_key: SecretStr
    buyer_agent_token: SecretStr
    data_root: Path
    runs_root: Path
    live: bool = False
    renderer_validated: bool = False
    jev_model: str = JEV_MODEL_PIN
    jev_timeout_s: int = 45
    jev_max_retries: int = 2
    jev_wait_for_s: int = 50
    judge_stage_cap_s: int = 120
    request_cap_s: int = 180
    groq_model_main: str = "openai/gpt-oss-120b"
    groq_model_fast: str = "openai/gpt-oss-20b"
    groq_timeout_s: int = 12
    groq_max_retries: int = 0
    advise_cap_s: int = 30
    concurrency: int = 4
    rate_per_hour: int = 10
    paid_calls_per_hour: int = 400
    attempts_per_id: int = 3
    max_body_bytes: int = 65_536
    auth_fail_per_10min: int = 20
    run_retention_days: int = 14
    render_max_points: int = 300_000
    claims_max_side: int = 768


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise AgentError(ErrorCode.INPUT_INVALID, f"missing required setting {name}")
    return value


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or DEFAULT_ENV_FILE)
    typesafe, groq, token = (
        _required(n) for n in ("TYPESAFE_API_KEY", "GROQ_API_KEY", "BUYER_AGENT_TOKEN")
    )
    data_root = Path(_required("DATA_ROOT"))
    if not data_root.is_absolute():
        data_root = REPO_ROOT / data_root
    if not data_root.is_dir():
        raise AgentError(ErrorCode.INPUT_INVALID, f"DATA_ROOT does not exist: {data_root}")
    return Settings(
        typesafe_api_key=SecretStr(typesafe),
        groq_api_key=SecretStr(groq),
        buyer_agent_token=SecretStr(token),
        data_root=data_root.resolve(),
        runs_root=PACKAGE_ROOT / "runs",
        live=_flag("BUYER_AGENT_LIVE"),
        renderer_validated=_flag("BUYER_AGENT_RENDERER_VALIDATED"),
    )
