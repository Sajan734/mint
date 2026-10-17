"""Jev (TypeSafe) client: protocol, live, replay. Keys come from Settings only, never at import."""

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from buyer_agent.config import JEV_MODEL_PIN, Settings
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.jev_prompts import IMAGES_HEADER

_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


@dataclass(frozen=True)
class JevAnswer:
    model: str
    nouls: dict[str, float]
    usage: dict[str, int | None] = field(default_factory=dict)
    latency_ms: int = 0
    timestamp: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class JevClient(Protocol):
    async def ask(self, state: dict, questions: dict, *, key: str = "") -> JevAnswer: ...


def map_jev_error(exc: BaseException) -> AgentError:
    """SDK / asyncio exception -> AgentError. Detail is for the run log only."""
    if isinstance(exc, AgentError):
        return exc
    if isinstance(exc, TimeoutError):  # asyncio.TimeoutError is TimeoutError on 3.11
        return AgentError(ErrorCode.JEV_TIMEOUT, "timeout")
    status = getattr(exc, "status", None)
    name = type(exc).__name__
    if status in (401, 403) or name in (
        "TypeSafeAuthenticationError",
        "TypeSafePermissionDeniedError",
    ):
        return AgentError(ErrorCode.JEV_AUTH, f"status {status}")
    if status == 429 or name == "TypeSafeRateLimitError":
        return AgentError(ErrorCode.JEV_RATE_LIMITED, "status 429")
    if name == "TypeSafeAPITimeoutError":
        return AgentError(ErrorCode.JEV_TIMEOUT, "sdk timeout")
    if name == "TypeSafeAPIResponseValidationError":
        return AgentError(ErrorCode.JEV_BAD_RESPONSE, "response validation")
    if status == 400:
        return AgentError(ErrorCode.IMAGE_INVALID, "status 400")
    return AgentError(ErrorCode.JEV_UNAVAILABLE, f"{name} status {status}")


def _parse_response(r: Any, started: float) -> JevAnswer:
    try:
        nouls = {k: float(a.noul) for k, a in r.nouls.items()}
        usage = {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}
        model = str(r.model)
    except (AttributeError, TypeError, ValueError) as exc:
        raise AgentError(ErrorCode.JEV_BAD_RESPONSE, "unexpected response shape") from exc
    return JevAnswer(
        model=model,
        nouls=nouls,
        usage=usage,
        latency_ms=int((time.monotonic() - started) * 1000),
        timestamp=datetime.now(UTC).isoformat(),
    )


class LiveJev:
    """Real client. Construction makes no network call."""

    def __init__(self, settings: Settings) -> None:
        from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

        self._wait_for = settings.jev_wait_for_s
        self._client = AsyncTypeSafeClient(
            api_key=settings.typesafe_api_key.get_secret_value(),
            model=JEV_MODEL_PIN,
            retry=RetryPolicy(
                max_retries=settings.jev_max_retries, timeout=float(settings.jev_timeout_s)
            ),
        )

    async def ask(
        self, state: dict, questions: dict, *, key: str = ""
    ) -> JevAnswer:  # pragma: no cover
        started = time.monotonic()
        try:
            r = await asyncio.wait_for(
                self._client.system_one(
                    state=state, questions=questions, extra_headers=IMAGES_HEADER
                ),
                self._wait_for,
            )
        except Exception as exc:
            raise map_jev_error(exc) from exc
        return _parse_response(r, started)

    async def aclose(self) -> None:  # pragma: no cover
        await self._client.aclose()


def save_recording(directory: Path, key: str, answer: JevAnswer) -> Path:
    if not _KEY_RE.fullmatch(key):
        raise AgentError(ErrorCode.INPUT_INVALID, f"bad recording key: {key!r}")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.json"
    path.write_text(json.dumps(asdict(answer), indent=1), encoding="utf-8")
    return path


class ReplayJev:
    """Serves recorded answers by key. Refuses recordings made by a model other than the pin."""

    def __init__(self, directory: Path, pin: str = JEV_MODEL_PIN) -> None:
        self._dir = Path(directory)
        self._pin = pin

    async def ask(self, state: dict, questions: dict, *, key: str = "") -> JevAnswer:
        if not _KEY_RE.fullmatch(key):
            raise AgentError(ErrorCode.INPUT_INVALID, f"bad recording key: {key!r}")
        path = self._dir / f"{key}.json"
        if not path.is_file():
            raise AgentError(ErrorCode.INTERNAL, f"no jev recording for key {key!r} in {self._dir}")
        try:
            answer = JevAnswer(**json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError) as exc:
            raise AgentError(ErrorCode.JEV_BAD_RESPONSE, f"unreadable recording {key!r}") from exc
        if answer.model != self._pin:
            raise AgentError(
                ErrorCode.INTERNAL,
                f"recording {key!r} was made by {answer.model!r}, pin is {self._pin!r}",
            )
        return answer
