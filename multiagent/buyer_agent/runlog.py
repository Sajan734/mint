"""Per-comparison run folder: atomic redacted writes, secret redaction helpers."""

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.models import CompareRequest, CompareResponse

REDACTED = "[REDACTED]"
_KEY_RE = re.compile(r"key|token|authorization|secret|password", re.IGNORECASE)
# ponytail: TypeSafe key prefix is unconfirmed; "typesafe/ts" + separator is a guess, tighten later
_SECRET_RE = re.compile(r"\b(?:gsk|typesafe|ts)[_-][A-Za-z0-9_\-]{8,}", re.IGNORECASE)
_known_secrets: set[str] = set()


def register_secrets(*values: str) -> None:
    """Remember loaded secret values so redact() strips them wherever they appear."""
    _known_secrets.update(v for v in values if len(v) >= 8)


def _redact_str(text: str) -> str:
    for secret in _known_secrets:
        text = text.replace(secret, REDACTED)
    return _SECRET_RE.sub(REDACTED, text)


def redact(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: REDACTED if _KEY_RE.search(str(k)) else redact(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [redact(v) for v in obj]
    return _redact_str(obj) if isinstance(obj, str) else obj


def safe_exc(e: BaseException) -> str:
    return f"{type(e).__name__}: {_redact_str(str(e))}"


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_str(record.getMessage())
        record.args = None
        return True


def install_log_redaction() -> None:
    """Redact secrets in every log record the process creates (package, uvicorn, libraries)."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "redacting", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.msg, record.args = _redact_str(record.getMessage()), None
        return record

    factory.redacting = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


class RunLog:
    def __init__(self, runs_root: Path, run_id: str) -> None:
        try:
            if str(UUID(run_id)) != run_id.lower():
                raise ValueError(run_id)
        except ValueError as e:
            raise AgentError(ErrorCode.INPUT_INVALID, "run_id must be a uuid") from e
        self.dir = Path(runs_root) / run_id.lower()

    def _target(self, name: str) -> Path:
        path = (self.dir / name).resolve()
        if not path.is_relative_to(self.dir.resolve()):
            raise AgentError(ErrorCode.INPUT_INVALID, f"path escapes run dir: {name}")
        return path

    def _atomic(self, name: str, data: bytes) -> Path:
        path = self._target(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return path

    def save_json(self, name: str, obj: Any) -> Path | None:
        """Write redacted JSON. A `status: failed` response.json is never persisted (AM-14)."""
        data = redact(obj)
        if name == "response.json" and isinstance(data, dict) and data.get("status") == "failed":
            return None
        return self._atomic(name, json.dumps(data, indent=2, sort_keys=True).encode())

    def save_png(self, name: str, png: bytes) -> Path:
        return self._atomic(name, png)

    def load_response(self) -> CompareResponse | None:
        path = self._target("response.json")
        if not path.is_file():
            return None
        return CompareResponse.model_validate_json(path.read_text(encoding="utf-8"))

    def save_failure_detail(self, view: str, detail: str) -> Path:
        slug = re.sub(r"[^A-Za-z0-9_-]", "_", view)[:80]
        return self._atomic(
            f"jev/failure_{slug}.json",
            json.dumps({"view": view, "detail": redact(detail)}).encode(),
        )

    @staticmethod
    def request_hash(req: CompareRequest) -> str:
        return hashlib.sha256(req.model_dump_json(exclude={"attempt"}).encode()).hexdigest()
