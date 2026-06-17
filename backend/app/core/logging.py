"""Structured JSON logging (Standards §8).

One JSON event per line on stdout. A request/correlation id flows via a
``ContextVar`` so every log line emitted while handling a request carries it.
Never log secrets, PII, or full payloads — callers pass small structured fields
via ``extra=...`` and avoid logging connection strings or tracebacks that could
embed credentials.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attribute names present on a vanilla LogRecord — anything else on a record was
# supplied via `extra=` and should be surfaced in the JSON output.
_STANDARD_RECORD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_ctx.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and key not in payload:
                payload[key] = value

        if record.exc_info:
            # exc_info is only attached where there is no secret-leak risk.
            exc_type = record.exc_info[0]
            payload["error_type"] = exc_type.__name__ if exc_type else None

        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Install the JSON formatter on the root logger and tame noisy libraries."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Route library logs through our handler (no duplicate handlers).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        lib_logger = logging.getLogger(name)
        lib_logger.handlers.clear()
        lib_logger.propagate = True

    # We emit our own structured access log; silence uvicorn's and quiet SQL echo.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
