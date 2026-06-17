"""Bounded retry/backoff (Standards §12), simulated with controllable failures."""

from __future__ import annotations

import pytest

from app.ai.errors import AIInvocationError, AITimeout, AITransientError
from app.ai.retry import with_retries

_RETRY_ON = (AITransientError, AITimeout)


def _noop(_delay: float) -> None:
    return None


def test_transient_failure_is_retried_then_succeeds() -> None:
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise AITransientError("transient")
        return "ok"

    result = with_retries(
        flaky,
        max_attempts=5,
        base_delay=0.0,
        max_delay=0.0,
        retry_on=_RETRY_ON,
        sleep=_noop,
    )
    assert result == "ok"
    assert attempts["n"] == 3


def test_persistent_failure_surfaces_typed_error_after_max_attempts() -> None:
    attempts = {"n": 0}

    def always_fail() -> str:
        attempts["n"] += 1
        raise AITimeout("always times out")

    with pytest.raises(AITimeout):
        with_retries(
            always_fail,
            max_attempts=3,
            base_delay=0.0,
            max_delay=0.0,
            retry_on=_RETRY_ON,
            sleep=_noop,
        )
    assert attempts["n"] == 3


def test_non_retryable_error_propagates_immediately() -> None:
    attempts = {"n": 0}

    def permanent() -> str:
        attempts["n"] += 1
        raise AIInvocationError("permanent")

    with pytest.raises(AIInvocationError):
        with_retries(
            permanent,
            max_attempts=3,
            base_delay=0.0,
            max_delay=0.0,
            retry_on=_RETRY_ON,
            sleep=_noop,
        )
    assert attempts["n"] == 1
