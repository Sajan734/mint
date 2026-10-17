"""HTTP API (U25). Run:
`.venv\\Scripts\\python -m uvicorn --factory buyer_agent.api:app_factory --host 127.0.0.1 --port 8765 --no-proxy-headers`
Keep `--no-proxy-headers`: limits are keyed on the socket peer, never on X-Forwarded-For.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from buyer_agent import sources
from buyer_agent.budget import WORST_CASE_CALLS, CallBudget
from buyer_agent.claims import FileClaimsProvider
from buyer_agent.config import PACKAGE_ROOT, Settings, load_settings
from buyer_agent.errors import AgentError, ErrorCode, user_message
from buyer_agent.groq_client import GroqClient
from buyer_agent.jev_client import JevClient
from buyer_agent.models import CompareRequest
from buyer_agent.pipeline import Deps, compare
from buyer_agent.retention import prune_runs
from buyer_agent.runlog import RedactingFilter, RunLog, install_log_redaction, register_secrets

log = logging.getLogger("buyer_agent.api")
log.addFilter(RedactingFilter())
HOUR_S, AUTH_WINDOW_S = 3600.0, 600.0
STATUS = {
    ErrorCode.INPUT_INVALID: 422,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.BUSY: 429,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.BUDGET_EXHAUSTED: 429,
    ErrorCode.ATTEMPTS_EXHAUSTED: 429,
}


class _Window:
    """Sliding-window counter per key. ponytail: in-memory, single process."""

    def __init__(self, limit: int, seconds: float, clock: Callable[[], float]) -> None:
        self.limit, self._seconds, self._clock = limit, seconds, clock
        self._hits: dict[Any, deque[float]] = defaultdict(deque)

    def full(self, key: Any) -> bool:
        hits, now = self._hits[key], self._clock()
        while hits and now - hits[0] >= self._seconds:
            hits.popleft()
        return len(hits) >= self.limit

    def add(self, key: Any) -> None:
        self._hits[key].append(self._clock())


def _error(code: ErrorCode) -> JSONResponse:
    body = {"error": {"code": code.value, "message": user_message(code)}}
    return JSONResponse(body, status_code=STATUS[code])


def _plain(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _default_clients(settings: Settings) -> tuple[JevClient, GroqClient]:
    if settings.live:
        from buyer_agent.groq_client import LiveGroq
        from buyer_agent.jev_client import LiveJev

        return LiveJev(settings), LiveGroq(settings)
    from buyer_agent.groq_client import ReplayGroq
    from buyer_agent.jev_client import ReplayJev

    replay = PACKAGE_ROOT / "tests" / "fixtures" / "replay"
    return ReplayJev(replay / "jev"), ReplayGroq(replay / "groq")


def _read_meta(run: RunLog) -> dict[str, Any] | None:
    try:
        meta = json.loads((run.dir / "meta.json").read_text(encoding="utf-8"))
        if isinstance(meta, dict) and isinstance(meta.get("executions"), int):
            return meta
        raise ValueError("bad meta shape")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # corrupt meta: treat as a fresh id, but say so
        log.warning("corrupt meta.json ignored")
        return None


def _prune(settings: Settings) -> None:
    """Cheap and bounded: only walks run folders. Never fails a request."""
    try:
        prune_runs(settings.runs_root, settings.run_retention_days, time.time())
    except OSError:
        log.warning("run prune failed")


def _stored_done(run: RunLog) -> dict[str, Any] | None:
    try:
        stored = run.load_response()
    except (OSError, ValueError, ValidationError):
        return None
    return stored.model_dump(mode="json") if stored and stored.status == "done" else None


def create_app(
    settings: Settings,
    *,
    jev: JevClient | None = None,
    groq: GroqClient | None = None,
    renderer: Any = None,
    claims_provider: Any = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    secrets_ = (settings.typesafe_api_key, settings.groq_api_key, settings.buyer_agent_token)
    register_secrets(*(s.get_secret_value() for s in secrets_))
    install_log_redaction()
    if jev is None or groq is None:
        default_jev, default_groq = _default_clients(settings)
        jev, groq = jev or default_jev, groq or default_groq
    if renderer is None:
        from buyer_agent.render import CpuPointRenderer

        renderer = CpuPointRenderer(settings.render_max_points)
    deps = Deps(
        settings=settings, jev=jev, groq=groq, renderer=renderer,
        runlog_factory=lambda rid: RunLog(settings.runs_root, rid),
        claims_provider=claims_provider or FileClaimsProvider(settings.data_root / "claims"),
        clock=clock,
    )  # fmt: skip
    token = settings.buyer_agent_token.get_secret_value().encode()
    token_id = hashlib.sha256(token).hexdigest()[:16]
    runs = _Window(settings.rate_per_hour, HOUR_S, clock)
    auth_fails = _Window(settings.auth_fail_per_10min, AUTH_WINDOW_S, clock)
    budget = CallBudget(settings.paid_calls_per_hour, clock)
    lock = asyncio.Lock()  # ponytail: one comparison at a time; per-listing locks if more traffic

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        register_secrets(*(s.get_secret_value() for s in secrets_))
        prune_runs(settings.runs_root, settings.run_retention_days, time.time())
        yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def authenticate(request: Request) -> JSONResponse | None:
        ip = _ip(request)
        if auth_fails.full(ip):
            return _error(ErrorCode.RATE_LIMITED)
        scheme, _, given = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and hmac.compare_digest(given.encode(), token):
            return None
        auth_fails.add(ip)
        log.warning("auth failure from %s", ip)
        return _plain(401, "UNAUTHORIZED", "Missing or invalid token.")

    async def execute(request: Request, req: CompareRequest) -> JSONResponse:
        run = RunLog(settings.runs_root, str(req.comparison_id))
        digest, meta = RunLog.request_hash(req), _read_meta(run)
        if meta and meta.get("body_sha256") != digest:
            return _plain(409, "CONFLICT", "This id was already used for a different request.")
        if meta and (stored := _stored_done(run)) is not None:
            return JSONResponse(stored)  # replay is free
        executions = int(meta["executions"]) if meta else 0
        if executions >= settings.attempts_per_id:
            return _error(ErrorCode.ATTEMPTS_EXHAUSTED)
        key = (token_id, _ip(request))
        if runs.full(key):
            return _error(ErrorCode.RATE_LIMITED)
        if lock.locked():
            return _error(ErrorCode.BUSY)
        async with lock:
            if not budget.try_take(WORST_CASE_CALLS):
                return _error(ErrorCode.BUDGET_EXHAUSTED)
            runs.add(key)
            _prune(settings)
            run.save_json("meta.json", {"body_sha256": digest, "executions": executions + 1})
            response = await compare(req, deps)
        return JSONResponse(response.model_dump(mode="json"))

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/v1/comparisons")
    async def post_comparison(request: Request) -> JSONResponse:
        if (denied := authenticate(request)) is not None:
            return denied
        length = request.headers.get("content-length", "")
        if not length.isdigit() or int(length) > settings.max_body_bytes:
            return _error(ErrorCode.PAYLOAD_TOO_LARGE)
        body = await request.body()
        if len(body) > settings.max_body_bytes:
            return _error(ErrorCode.PAYLOAD_TOO_LARGE)
        try:
            req = CompareRequest.model_validate_json(body)
            sources.validate_request_paths(req)
        except (ValidationError, ValueError, AgentError):
            return _error(ErrorCode.INPUT_INVALID)
        return await execute(request, req)

    @app.get("/v1/comparisons/{comparison_id}")
    async def get_comparison(comparison_id: str, request: Request) -> JSONResponse:
        if (denied := authenticate(request)) is not None:
            return denied
        try:
            stored = RunLog(Path(settings.runs_root), str(UUID(comparison_id))).load_response()
        except (ValueError, OSError, ValidationError, AgentError):
            stored = None
        if stored is None:
            return _plain(404, "NOT_FOUND", "No such comparison.")
        return JSONResponse(stored.model_dump(mode="json"))

    return app


def app_factory() -> FastAPI:
    """uvicorn --factory entry point. The only place settings (env) are loaded."""
    return create_app(load_settings())
