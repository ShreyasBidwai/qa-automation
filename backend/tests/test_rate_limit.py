"""Rate limiting (B11, ADR-0046) — deterministic, clock-controlled (no sleeps).

Unit tests drive the limiter directly with a fake clock; endpoint tests override
``app.state.rate_limiter`` with a small, clock-controlled limiter so the 429 +
reset behaviour is exercised through the real auth routes without timing flakiness.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.core.rate_limit import (
    PASSWORD_RESET,
    SIGNIN,
    SIGNUP,
    RateLimiter,
    RateLimitRule,
)


class _Clock:
    """A controllable monotonic clock (seconds)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --- unit: the limiter -------------------------------------------------------


def test_allows_under_limit_then_blocks_then_resets() -> None:
    clock = _Clock()
    limiter = RateLimiter({"x": RateLimitRule(limit=3, window_seconds=60)}, clock=clock)

    for _ in range(3):  # under the limit → allowed
        assert limiter.hit("x", "ip1").allowed

    blocked = limiter.hit("x", "ip1")  # the 4th exceeds
    assert not blocked.allowed
    assert blocked.retry_after > 0
    assert not limiter.hit("x", "ip1").allowed  # still blocked within the window

    clock.advance(60)  # window elapsed → reset
    assert limiter.hit("x", "ip1").allowed


def test_identities_have_independent_windows() -> None:
    limiter = RateLimiter(
        {"x": RateLimitRule(limit=1, window_seconds=60)}, clock=_Clock()
    )
    assert limiter.hit("x", "a").allowed
    assert not limiter.hit("x", "a").allowed  # "a" exhausted
    assert limiter.hit("x", "b").allowed  # "b" has its own window


def test_unconfigured_name_is_never_limited() -> None:
    limiter = RateLimiter({}, clock=_Clock())
    for _ in range(50):
        result = limiter.hit("nope", "a")
        assert result.allowed and result.remaining == -1


# --- endpoint: 429 through the real auth routes ------------------------------


async def test_signin_429_after_threshold_then_resets(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    clock = _Clock()
    app.state.rate_limiter = RateLimiter(
        {SIGNIN: RateLimitRule(limit=2, window_seconds=60)}, clock=clock
    )
    body = {"email": "nobody@example.test", "password": "whatever1"}

    # Under the limit: the handler runs → 401 (no such account), NOT 429.
    for _ in range(2):
        assert (await client.post("/api/v1/auth/signin", json=body)).status_code == 401

    blocked = await client.post("/api/v1/auth/signin", json=body)
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After") is not None

    clock.advance(60)  # window resets → allowed through again (401)
    assert (await client.post("/api/v1/auth/signin", json=body)).status_code == 401


async def test_signup_and_reset_request_are_rate_limited(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    app.state.rate_limiter = RateLimiter(
        {
            SIGNUP: RateLimitRule(limit=1, window_seconds=60),
            PASSWORD_RESET: RateLimitRule(limit=1, window_seconds=60),
        },
        clock=_Clock(),
    )

    def _signup_body() -> dict[str, str]:
        return {
            "email": f"u-{uuid.uuid4().hex[:10]}@example.test",
            "password": "str0ngpass",
        }

    # signup: first allowed (201), second over the limit (429).
    first = await client.post("/api/v1/auth/signup", json=_signup_body())
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/signup", json=_signup_body())
    assert second.status_code == 429

    # password-reset request: first allowed (202, always silent), second 429.
    reset_body = {"email": "someone@example.test"}
    assert (
        await client.post("/api/v1/auth/password-reset/request", json=reset_body)
    ).status_code == 202
    assert (
        await client.post("/api/v1/auth/password-reset/request", json=reset_body)
    ).status_code == 429
