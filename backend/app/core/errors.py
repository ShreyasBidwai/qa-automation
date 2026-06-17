"""RFC-9457 problem+json error handling (Standards §7).

Returns ``application/problem+json`` with a stable, machine-readable ``code``.
Never leaks stack traces or secrets to clients; unexpected errors are logged by
type only.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.error")

PROBLEM_CONTENT_TYPE = "application/problem+json"


def _problem(
    status: int,
    title: str,
    *,
    detail: str | None = None,
    code: str,
) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    body["code"] = code
    return JSONResponse(
        status_code=status, content=body, media_type=PROBLEM_CONTENT_TYPE
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    status = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    detail = (
        str(exc.detail)
        if isinstance(exc, StarletteHTTPException) and exc.detail
        else None
    )
    title = HTTPStatus(status).phrase
    return _problem(status, title, detail=detail, code=f"http_{status}")


async def _validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    # Do not echo the offending payload back (no PII / no full payloads).
    return _problem(
        422,
        "Unprocessable Entity",
        detail="Request validation failed.",
        code="validation_error",
    )


async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.error("unhandled exception", extra={"error_type": type(exc).__name__})
    return _problem(
        500, "Internal Server Error", code="internal_error"
    )  # no detail, no traceback


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
