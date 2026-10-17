"""Groq client: protocol, live, replay. Llama gets json_object only (no json_schema)."""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from buyer_agent.config import Settings
from buyer_agent.errors import AgentError, ErrorCode

_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
TEMPERATURE = 0.3
MAX_COMPLETION_TOKENS = 700
_NO_STATUS_RETRYABLE = ("APITimeoutError", "APIConnectionError", "TimeoutError")


class GroqCallError(Exception):
    """`retryable`: 429 / 5xx / timeout / connection (try the fast model). 400/401/403: not."""

    def __init__(self, retryable: bool, detail: str = "") -> None:
        super().__init__("groq call failed")
        self.retryable = retryable
        self.detail = detail


@dataclass(frozen=True)
class GroqAnswer:
    model: str
    text: str
    usage: dict[str, int | None] = field(default_factory=dict)
    latency_ms: int = 0


class GroqClient(Protocol):
    async def chat(self, model: str, system: str, user: str, *, key: str = "") -> GroqAnswer: ...


def classify_groq_error(exc: BaseException) -> GroqCallError:
    if isinstance(exc, GroqCallError):
        return exc
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    if status is None:  # timeouts / connection errors carry no status
        return GroqCallError(name in _NO_STATUS_RETRYABLE, name)
    return GroqCallError(status == 429 or status >= 500, f"status {status}")


class LiveGroq:
    """Real client. Construction makes no network call."""

    def __init__(self, settings: Settings) -> None:
        from groq import AsyncGroq

        self._client = AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(),
            timeout=float(settings.groq_timeout_s),
            max_retries=settings.groq_max_retries,
        )

    async def chat(
        self, model: str, system: str, user: str, *, key: str = ""
    ) -> GroqAnswer:  # pragma: no cover
        if "json" not in (system + user).lower():  # Groq 400s json_object without the word
            raise GroqCallError(False, "prompt must contain the word JSON")
        started = time.monotonic()
        try:
            r = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=TEMPERATURE,
                max_completion_tokens=MAX_COMPLETION_TOKENS,
                response_format={"type": "json_object"},
            )
            text = r.choices[0].message.content or ""
            usage = {
                "input_tokens": getattr(r.usage, "prompt_tokens", None),
                "output_tokens": getattr(r.usage, "completion_tokens", None),
            }
        except Exception as exc:
            raise classify_groq_error(exc) from exc
        return GroqAnswer(model, text, usage, int((time.monotonic() - started) * 1000))


def save_recording(directory: Path, key: str, answer: GroqAnswer) -> Path:
    if not _KEY_RE.fullmatch(key):
        raise AgentError(ErrorCode.INPUT_INVALID, f"bad recording key: {key!r}")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.json"
    path.write_text(json.dumps(asdict(answer), indent=1), encoding="utf-8")
    return path


class ReplayGroq:
    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)

    async def chat(self, model: str, system: str, user: str, *, key: str = "") -> GroqAnswer:
        if not _KEY_RE.fullmatch(key):
            raise AgentError(ErrorCode.INPUT_INVALID, f"bad recording key: {key!r}")
        path = self._dir / f"{key}.json"
        if not path.is_file():
            raise AgentError(
                ErrorCode.INTERNAL, f"no groq recording for key {key!r} in {self._dir}"
            )
        return GroqAnswer(**json.loads(path.read_text(encoding="utf-8")))
