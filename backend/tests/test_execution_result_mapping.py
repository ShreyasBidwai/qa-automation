"""Result mapping — canned JUnit cases → ExecutionResult rows, by script stem."""

from __future__ import annotations

import uuid

from app.execution.junit import JUnitCase
from app.execution.php_test_runner import map_results
from app.execution.types import PestScript
from app.models.enums import Outcome


def _script(name: str) -> PestScript:
    return PestScript(
        test_case_id=uuid.uuid4(),
        script_id=uuid.uuid4(),
        name=name,
        code="<?php // ...",
    )


def _case(stem: str, outcome: Outcome, message: str | None = None) -> JUnitCase:
    return JUnitCase(
        name=stem,
        classname=None,
        file=f"/app/tests/Feature/_generated/{stem}.php",
        outcome=outcome,
        message=message,
    )


def test_maps_outcomes_and_carries_evidence_ref() -> None:
    scripts = [_script("happy"), _script("missing")]
    cases = [
        _case("happy", Outcome.PASS),
        _case("missing", Outcome.FAIL, "expected 201, got 422"),
    ]
    results = map_results(scripts, cases, evidence_ref="/ev/pest-junit.xml")

    by_name = {r.name: r for r in results}
    assert by_name["happy"].outcome is Outcome.PASS
    assert by_name["missing"].outcome is Outcome.FAIL
    assert by_name["missing"].message == "expected 201, got 422"
    # Identity is preserved so the lifecycle can write the right results rows.
    assert by_name["happy"].test_case_id == scripts[0].test_case_id
    assert all(r.evidence_ref == "/ev/pest-junit.xml" for r in results)


def test_script_without_a_result_becomes_error() -> None:
    scripts = [_script("ran"), _script("never_ran")]
    cases = [_case("ran", Outcome.PASS)]
    results = map_results(scripts, cases, evidence_ref="/ev/x.xml")

    by_name = {r.name: r for r in results}
    assert by_name["ran"].outcome is Outcome.PASS
    assert by_name["never_ran"].outcome is Outcome.ERROR
    assert by_name["never_ran"].message == "no test result produced for script"


def test_maps_when_file_attr_carries_pest_test_name_suffix() -> None:
    # Pest emits file="<relpath>.php::<test name>"; the stem must still match.
    scripts = [_script("happy")]
    cases = [
        JUnitCase(
            name="store user happy path",
            classname="Tests\\Feature\\generated\\happy",
            file="tests/Feature/_generated/happy.php::store user happy path",
            outcome=Outcome.PASS,
            message=None,
        )
    ]
    results = map_results(scripts, cases, evidence_ref=None)
    assert results[0].name == "happy"
    assert results[0].outcome is Outcome.PASS


def test_multiple_cases_per_script_take_the_worst_outcome() -> None:
    scripts = [_script("multi")]
    cases = [
        _case("multi", Outcome.PASS),
        _case("multi", Outcome.FAIL, "assertion failed"),
    ]
    results = map_results(scripts, cases, evidence_ref=None)
    assert results[0].outcome is Outcome.FAIL
    assert results[0].message == "assertion failed"


def test_skip_only_script_aggregates_to_skipped_not_pass() -> None:
    # A script whose only case was SKIPPED (reachable-but-unverified, or an
    # unavailable-factory skip) must aggregate to SKIPPED — NOT a silent pass that would
    # wrongly count toward pass-rate and seed a heal candidate (ADR-0064).
    scripts = [_script("skipme")]
    cases = [_case("skipme", Outcome.SKIPPED, "reachable but unverified: HTTP 404")]
    results = map_results(scripts, cases, evidence_ref=None)
    assert results[0].outcome is Outcome.SKIPPED


def test_pass_plus_skip_in_one_script_still_passes() -> None:
    # A verified pass alongside a skip still aggregates to PASS (something was proven).
    scripts = [_script("mixed")]
    cases = [_case("mixed", Outcome.PASS), _case("mixed", Outcome.SKIPPED)]
    results = map_results(scripts, cases, evidence_ref=None)
    assert results[0].outcome is Outcome.PASS
