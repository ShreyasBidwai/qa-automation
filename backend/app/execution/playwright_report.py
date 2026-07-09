"""Parse Playwright's JSON report into per-spec outcomes.

The JUnit reporter's file/classname mapping varies across Playwright versions, so
the runner parses the **JSON** report (a stable, documented shape) to map each
spec back to its source file reliably. JUnit is still written as evidence.

Pure and deterministic: input is the trusted JSON our own runner produced; output
is one ``PlaywrightCase`` per spec (a ``test()`` in a ``.spec.ts`` file). A spec's
outcome aggregates its test results — failed → FAIL, timed-out / interrupted /
skipped (did-not-complete) → ERROR, otherwise PASS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.models.enums import Outcome

from .errors import PlaywrightReportError

# Playwright result.status → our contract Outcome. "failed" is a genuine test
# failure; timedOut/interrupted did not complete (ERROR); "skipped" is a deliberate
# skip — reachable-but-unverified, neither pass nor fail (SKIPPED, ADR-0064).
_STATUS_OUTCOME: dict[str, Outcome] = {
    "passed": Outcome.PASS,
    "failed": Outcome.FAIL,
    "timedOut": Outcome.ERROR,
    "interrupted": Outcome.ERROR,
    "skipped": Outcome.SKIPPED,
}


@dataclass(frozen=True)
class PlaywrightCase:
    file: str  # spec file path as reported (e.g. "happy.spec.ts")
    title: str
    outcome: Outcome
    message: str | None


def _worst(outcomes: list[Outcome]) -> Outcome:
    # Severity order: a real defect/crash dominates; then a verified pass; a suite that
    # only SKIPPED (nothing pass/fail/error) is itself SKIPPED, not a silent pass.
    if Outcome.ERROR in outcomes:
        return Outcome.ERROR
    if Outcome.FAIL in outcomes:
        return Outcome.FAIL
    if Outcome.PASS in outcomes:
        return Outcome.PASS
    if Outcome.SKIPPED in outcomes:
        return Outcome.SKIPPED
    return Outcome.PASS


def _result_outcome(status: str) -> Outcome:
    # An unknown status is treated as ERROR rather than silently passing.
    return _STATUS_OUTCOME.get(status, Outcome.ERROR)


def _first_error_message(results: list[dict[str, Any]]) -> str | None:
    for result in results:
        if _result_outcome(str(result.get("status", ""))) is Outcome.PASS:
            continue
        error = result.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"]).strip() or None
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and first.get("message"):
                return str(first["message"]).strip() or None
    return None


def _spec_to_case(spec: dict[str, Any]) -> PlaywrightCase:
    results: list[dict[str, Any]] = []
    for test in spec.get("tests", []):
        if isinstance(test, dict):
            results.extend(r for r in test.get("results", []) if isinstance(r, dict))

    if results:
        outcome = _worst([_result_outcome(str(r.get("status", ""))) for r in results])
    else:
        # A spec the reporter listed but never ran (no results) did not complete.
        outcome = Outcome.ERROR

    return PlaywrightCase(
        file=str(spec.get("file", "")),
        title=str(spec.get("title", "")),
        outcome=outcome,
        message=_first_error_message(results),
    )


def _collect_specs(suite: dict[str, Any], out: list[PlaywrightCase]) -> None:
    """Recurse a suite tree, emitting one case per spec (deterministic order)."""
    for spec in suite.get("specs", []):
        if isinstance(spec, dict):
            out.append(_spec_to_case(spec))
    for child in suite.get("suites", []):
        if isinstance(child, dict):
            _collect_specs(child, out)


def parse_playwright_json(text: str) -> list[PlaywrightCase]:
    try:
        report = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlaywrightReportError("could not parse Playwright JSON report") from exc
    if not isinstance(report, dict):
        raise PlaywrightReportError("Playwright JSON report is not an object")

    cases: list[PlaywrightCase] = []
    for suite in report.get("suites", []):
        if isinstance(suite, dict):
            _collect_specs(suite, cases)
    return cases
