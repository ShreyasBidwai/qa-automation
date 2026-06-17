"""Bounded retry with exponential backoff + jitter (Standards §12).

Retries only the exception types named in ``retry_on``; any other exception
propagates immediately (no silent swallow). After the attempt budget is
exhausted, the last retryable error is re-raised (a typed error surfaces).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger("app.ai")

T = TypeVar("T")


def with_retries(
    func: Callable[[], T],
    *,
    max_attempts: int,
    base_delay: float,
    max_delay: float,
    retry_on: tuple[type[Exception], ...],
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> T:
    jitter = rng or random.Random()
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            # Re-raise anything not explicitly retryable, and the final attempt.
            if not isinstance(exc, retry_on) or attempt >= max_attempts:
                raise
            delay = min(base_delay * 2 ** (attempt - 1), max_delay)
            delay += jitter.uniform(0, base_delay)
            logger.warning(
                "ai.retry",
                extra={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "error_type": type(exc).__name__,
                    "delay_seconds": round(delay, 3),
                },
            )
            sleep(delay)
    raise RuntimeError("with_retries: unreachable")  # pragma: no cover
