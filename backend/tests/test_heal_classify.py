"""The deterministic spine (B8, ADR-0040) — the load-bearing safety rule.

A location failure is a candidate heal; an assertion failure is a real finding and
is NEVER healed. The classifier is model-free and biased toward ASSERTION: only
clear location evidence overrides the safe default. These tests pin that bias.
"""

from __future__ import annotations

import pytest

from app.healing.classify import (
    FailureClass,
    classify_failure,
    is_location_failure,
)
from app.models.enums import Outcome

FAIL = Outcome.FAIL


# --- LOCATION: couldn't reach the target → candidate heal --------------------


@pytest.mark.parametrize(
    "message",
    [
        "Expected response status code [200] but received [404].",
        "Expected response status code [422] but received [404].",  # negative test, route moved
        "GET /api/people failed: but received 404",
        "Symfony\\Component\\HttpKernel\\Exception\\NotFoundHttpException",
        "RouteNotFoundException: Route [users.store] not defined.",
        "404 Not Found",
        'locator.click: Timeout 30000ms exceeded.\nwaiting for selector "#submit"',
        "Error: element not found for selector .checkout-btn",
        "no node found for selector: [data-test=email]",
    ],
)
def test_location_failures_are_candidate_heals(message: str) -> None:
    assert classify_failure(FAIL, message) is FailureClass.LOCATION
    assert is_location_failure(FAIL, message) is True


# --- ASSERTION: reached it, value/behaviour wrong → NEVER healed -------------


@pytest.mark.parametrize(
    "message",
    [
        # the canonical regression: a 200 became a 500.
        "Expected response status code [200] but received [500]. "
        "Failed asserting that 500 is identical to 200.",
        # validation removed — a real behaviour change, not a move.
        "Expected response status code [422] but received [200].",
        "Failed asserting that two arrays are identical.",
        "assertJson: response does not match expected structure.",
        # a Playwright value mismatch that prints a number must NOT read as a 404.
        'expect(received).toBe(expected)\nExpected: 200\nReceived: 404',
        'expect(locator).toHaveText("Welcome")\nReceived string: "Goodbye"',
        # a body assertion that merely mentions "not found" is still an assertion.
        "Failed asserting that 'User not found' contains 'Welcome'.",
    ],
)
def test_assertion_failures_are_never_heals(message: str) -> None:
    assert classify_failure(FAIL, message) is FailureClass.ASSERTION
    assert is_location_failure(FAIL, message) is False


# --- the safe default: ambiguity, infra errors, empties → ASSERTION ----------


@pytest.mark.parametrize(
    "outcome,message",
    [
        (Outcome.FAIL, None),
        (Outcome.FAIL, ""),
        (Outcome.FAIL, "Something went wrong."),
        (Outcome.ERROR, "Fatal error: connection reset by peer"),
        (Outcome.ERROR, "PHP Fatal error: Uncaught TypeError"),
        # a pass never reaches the healer; defensively it is not a location heal.
        (Outcome.PASS, None),
    ],
)
def test_ambiguous_or_infra_defaults_to_assertion(
    outcome: Outcome, message: str | None
) -> None:
    # Under-healing is safe; over-healing is not. Anything not clearly a location
    # failure stays an assertion/finding and is never auto-healed.
    assert classify_failure(outcome, message) is FailureClass.ASSERTION
