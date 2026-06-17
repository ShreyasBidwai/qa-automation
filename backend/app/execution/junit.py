"""Parse Pest/PHPUnit ``--log-junit`` output into per-test outcomes.

Pure and deterministic: input is the trusted JUnit XML our own runner produced;
output is one ``JUnitCase`` per ``<testcase>``. A testcase with a ``<failure>``
child is a FAIL, an ``<error>`` (or ``<skipped>``, which we treat as not-run) is
an ERROR, and a bare testcase is a PASS.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree.ElementTree import Element, ParseError, fromstring

from app.models.enums import Outcome

from .errors import JUnitParseError


@dataclass(frozen=True)
class JUnitCase:
    name: str
    classname: str | None
    file: str | None
    outcome: Outcome
    message: str | None


def _message(testcase: Element, tag: str) -> str | None:
    child = testcase.find(tag)
    if child is None:
        return None
    return (child.get("message") or (child.text or "").strip()) or None


def _outcome(testcase: Element) -> tuple[Outcome, str | None]:
    if testcase.find("error") is not None:
        return Outcome.ERROR, _message(testcase, "error")
    if testcase.find("failure") is not None:
        return Outcome.FAIL, _message(testcase, "failure")
    if testcase.find("skipped") is not None:
        # No SKIP outcome in the contract; a skipped test did not execute.
        return Outcome.ERROR, "test skipped"
    return Outcome.PASS, None


def parse_junit(xml: str) -> list[JUnitCase]:
    try:
        root = fromstring(xml)
    except ParseError as exc:
        raise JUnitParseError("could not parse JUnit XML") from exc

    cases: list[JUnitCase] = []
    for testcase in root.iter("testcase"):
        outcome, message = _outcome(testcase)
        cases.append(
            JUnitCase(
                name=testcase.get("name", ""),
                classname=testcase.get("classname") or testcase.get("class"),
                file=testcase.get("file"),
                outcome=outcome,
                message=message,
            )
        )
    return cases
