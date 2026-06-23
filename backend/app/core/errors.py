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
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    body["code"] = code
    if errors:
        body["errors"] = errors
    return JSONResponse(
        status_code=status,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers,
    )


def _field_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    """Per-field messages (field name + message ONLY — never the input value).

    Surfaces honest, voiced validation messages (e.g. the password policy) without
    echoing the offending payload back. Pydantic prefixes custom ValueErrors with
    "Value error, "; we strip it so the message reads in the interface's voice.
    """
    out: list[dict[str, str]] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        message = str(err.get("msg", "")).removeprefix("Value error, ")
        out.append({"field": loc or "request", "message": message})
    return out


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    status = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    detail = (
        str(exc.detail)
        if isinstance(exc, StarletteHTTPException) and exc.detail
        else None
    )
    title = HTTPStatus(status).phrase
    # Preserve safe response headers set on the exception (e.g. Retry-After on a 429
    # from the rate limiter, B11) — the problem+json reformat must not drop them.
    headers = getattr(exc, "headers", None)
    return _problem(
        status, title, detail=detail, code=f"http_{status}", headers=headers
    )


async def _validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    # Echo per-field messages (additive ``errors``) so the interface can voice them;
    # never the offending payload itself (no PII / no full payloads).
    errors = _field_errors(exc) if isinstance(exc, RequestValidationError) else None
    return _problem(
        422,
        "Unprocessable Entity",
        detail="Request validation failed.",
        code="validation_error",
        errors=errors,
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
