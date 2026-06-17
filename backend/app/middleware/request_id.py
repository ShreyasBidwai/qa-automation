"""Correlation/request-id middleware (Standards §8, §11).

Reads an inbound request-id header or generates one, binds it to the logging
``ContextVar`` for the duration of the request, echoes it back on the response,
and emits a single structured access-log line per request.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from ..core.logging import request_id_ctx

logger = logging.getLogger("app.access")

_QUIET_PATHS = frozenset({"/healthz", "/readyz"})


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(self.header_name) or str(uuid4())
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            response.headers[self.header_name] = request_id
            level = logging.DEBUG if request.url.path in _QUIET_PATHS else logging.INFO
            logger.log(
                level,
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            request_id_ctx.reset(token)
