"""The deterministic spine (B8, ADR-0040) — classify a failure, model-free.

A newly-failing test that was passing before is one of two things, and the whole
safety of self-healing rests on telling them apart WITHOUT a model:

  - LOCATION failure — the test could not *reach/resolve* its target: the route
    404'd, the element/selector wasn't found, the page didn't resolve. The target
    likely moved, not broke → a candidate for an addressing heal.
  - ASSERTION failure — the test reached its target but the *value/status/
    behaviour* was wrong: a 200 became a 500, the body changed, an expectation
    didn't hold. This is a real finding → it must NEVER be healed.

This split is pure pattern matching over the failure text, and it is biased: when
the signal is anything other than an unambiguous location failure, we classify
ASSERTION. Under-healing is safe (a missed heal is just a surfaced failure);
over-healing is not (it rewrites past a real regression). So "assertion" is the
default, and only clear location evidence overrides it.
"""

from __future__ import annotations

import enum
import re

from app.models.enums import Outcome


class FailureClass(str, enum.Enum):
    """How a failing test failed — the input to the heal/no-heal decision."""

    LOCATION = "location"  # couldn't reach the target → candidate heal
    ASSERTION = "assertion"  # reached it, value/behaviour wrong → real finding


# An HTTP status the test actually received, e.g. Laravel/Pest's
# "Expected response status code [201] but received [404]." We read the *received*
# code: 404 means the route isn't where the test looked (a location failure);
# any other mismatch (500, an unexpected 2xx/4xx) means the route was reached and
# answered wrongly (an assertion failure). Anchored to the assertStatus phrasing
# (a bracketed code, or "but received N") so a generic value assertion that prints
# "Received: 404" as a compared *value* is not mistaken for an HTTP status.
_RECEIVED_STATUS_RE = re.compile(r"received\s*\[(\d{3})\]|but received\s+(\d{3})")

# Statuses that mean "the addressed target isn't there" rather than "it answered
# wrongly". Kept deliberately narrow (just 404) — 405/410 are arguably addressing
# too, but the safe default already protects us, so we only promote the
# unambiguous case to LOCATION.
_NOT_FOUND_STATUSES = frozenset({404})

# An explicit assertion macro fired → the target was reached and a value/behaviour
# check failed. Checked BEFORE the loose location keywords so a body assertion that
# merely mentions "not found" (e.g. asserting a 'User not found' message) is not
# mistaken for an addressing failure.
_ASSERTION_MARKERS: tuple[str, ...] = (
    "failed asserting",
    "assertjson",
    "assertexactjson",
    "assertsee",
    "assertdatabasehas",
    "assertdatabasemissing",
    "expect(",
    ".tobe",
    ".toequal",
    ".tohavetext",
    ".tohavevalue",
    ".tocontain",
    "tohavebeencalled",
    "does not match expected",
)

# Unambiguous "couldn't reach the target" signals from HTTP routers and browser
# drivers. Only consulted after the assertion markers are ruled out.
_LOCATION_MARKERS: tuple[str, ...] = (
    "element not found",
    "no element",
    "no node found",
    "unable to find element",
    "unable to locate element",
    "waiting for selector",
    "waiting for locator",
    "locator resolved to 0",
    "0 element(s)",
    "selector did not match",
    "no route",
    "route not found",
    "routenotfoundexception",
    "notfoundhttpexception",
    "could not be resolved",
    "404 not found",
)


def _received_status(message: str) -> int | None:
    match = _RECEIVED_STATUS_RE.search(message)
    if match is None:
        return None
    return int(match.group(1) or match.group(2))


def classify_failure(outcome: Outcome, message: str | None) -> FailureClass:
    """Classify one failing test as a LOCATION or ASSERTION failure.

    Deterministic and side-effect-free. ``outcome`` is the persisted result
    outcome (``fail``/``error``); a ``pass`` is not a failure and never reaches the
    healer, so it is treated as an assertion (no-op, never healed) defensively.
    The decision order encodes the safety bias:

      1. a *received* 404 → LOCATION (the canonical "route moved" signal);
      2. an explicit assertion macro → ASSERTION (reached, value wrong);
      3. an unambiguous location marker → LOCATION;
      4. anything else, including an empty/ambiguous message or an infra error →
         ASSERTION (the safe default: never heal unless we are sure).
    """
    if outcome is Outcome.PASS:
        return FailureClass.ASSERTION
    text = (message or "").lower()

    received = _received_status(text)
    if received is not None:
        # A status-shaped failure: 404 = not where we looked (location); any other
        # received code = reached and answered wrongly (assertion).
        if received in _NOT_FOUND_STATUSES:
            return FailureClass.LOCATION
        return FailureClass.ASSERTION

    if any(marker in text for marker in _ASSERTION_MARKERS):
        return FailureClass.ASSERTION
    if any(marker in text for marker in _LOCATION_MARKERS):
        return FailureClass.LOCATION
    return FailureClass.ASSERTION


def is_location_failure(outcome: Outcome, message: str | None) -> bool:
    """True iff this failure is a candidate for an addressing heal."""
    return classify_failure(outcome, message) is FailureClass.LOCATION
