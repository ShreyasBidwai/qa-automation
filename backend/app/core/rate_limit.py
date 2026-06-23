"""In-memory fixed-window rate limiter for sensitive auth endpoints (B11).

Hygiene before exposure, not a moat: blunt brute-force on sign-in and abuse of
sign-up / password-reset by capping requests per identity per window.

**Single-instance caveat (ADR-0046):** counters live in THIS process's memory.
Behind multiple replicas each holds its own window, so the effective limit is
per-replica, and a restart clears the counters. That's acceptable to slow obvious
abuse before launch; a shared store (Redis) is the next step for real horizontal
deployment. No persistence → no migration.

The clock is injectable so window + reset behaviour is exercised deterministically
in tests (no sleeps).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings


@dataclass(frozen=True)
class RateLimitRule:
    limit: int  # max allowed requests within the window
    window_seconds: float


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int  # requests left in the window (-1 when the name is unconfigured)
    retry_after: int  # seconds until the window resets (0 when allowed)


class RateLimiter:
    """Fixed-window counters keyed by ``name:identity``, in-process.

    A window starts at the first hit and lasts ``window_seconds``; the count resets
    once it elapses. Deterministic given a deterministic clock.
    """

    def __init__(
        self,
        rules: dict[str, RateLimitRule],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rules = rules
        self._clock = clock
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, name: str, identity: str) -> RateLimitResult:
        """Record one request against ``name`` for ``identity`` and decide it."""
        rule = self._rules.get(name)
        if rule is None:  # an unconfigured endpoint is never limited
            return RateLimitResult(allowed=True, remaining=-1, retry_after=0)

        now = self._clock()
        key = f"{name}:{identity}"
        start, count = self._windows.get(key, (now, 0))
        if now - start >= rule.window_seconds:  # window elapsed → reset
            start, count = now, 0
        count += 1
        self._windows[key] = (start, count)

        if count > rule.limit:
            retry_after = max(1, int(rule.window_seconds - (now - start)))
            return RateLimitResult(allowed=False, remaining=0, retry_after=retry_after)
        return RateLimitResult(
            allowed=True, remaining=rule.limit - count, retry_after=0
        )


# Logical names for the limited endpoints (shared by the builder + the dependency).
SIGNIN = "auth_signin"
SIGNUP = "auth_signup"
PASSWORD_RESET = "auth_password_reset"


def build_rate_limiter(settings: Settings) -> RateLimiter:
    """The process-wide limiter for the auth endpoints, configured from settings."""
    window = settings.auth_rate_limit_window_seconds
    return RateLimiter(
        {
            SIGNIN: RateLimitRule(settings.auth_signin_rate_limit, window),
            SIGNUP: RateLimitRule(settings.auth_signup_rate_limit, window),
            PASSWORD_RESET: RateLimitRule(
                settings.auth_password_reset_rate_limit, window
            ),
        }
    )
