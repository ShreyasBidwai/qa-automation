"""Per-IP rate-limit dependency for the sensitive auth endpoints (B11, ADR-0046).

A route declares ``dependencies=[Depends(rate_limited(SIGNIN))]``; this reads the
process-wide limiter from ``app.state.rate_limiter`` (composed at startup), keys by
client IP, and raises a clear ``429`` with a ``Retry-After`` header when the window
is exceeded. If no limiter is configured (e.g. a test that didn't set one), it is a
no-op — limiting is opt-in via composition.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request

from app.core.rate_limit import RateLimiter


def _client_ip(request: Request) -> str:
    """The caller's IP for keying. Behind a trusted proxy this is the proxy unless
    proxy headers are honored upstream — noted as a deployment caveat in ADR-0046."""
    return request.client.host if request.client is not None else "unknown"


def rate_limited(name: str) -> Callable[[Request], Awaitable[None]]:
    """A FastAPI dependency that enforces the ``name`` limit per client IP."""

    async def _dependency(request: Request) -> None:
        limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter is None:
            return  # not configured → no limiting
        result = limiter.hit(name, _client_ip(request))
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — slow down and try again shortly.",
                headers={"Retry-After": str(result.retry_after)},
            )

    return _dependency
