"""PhpTestRunner — detects the target's test binary (Pest OR PHPUnit), parses both.

The target app may ship Pest (``vendor/bin/pest``) or vanilla PHPUnit
(``vendor/bin/phpunit``); the runner must use whichever exists (Pest preferred) and
fail with a clear error when neither does. Both runners accept ``--log-junit`` and
emit standard JUnit XML, so result parsing is runner-agnostic — proven here against
both a Pest-shaped and a real PHPUnit-shaped JUnit document.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from app.execution.errors import RunnerProcessError
from app.execution.junit import parse_junit
from app.execution.php_test_runner import (
    PhpTestRunner,
    detect_test_binary,
    map_results,
)
from app.execution.process import ProcessResult
from app.execution.types import (
    DbHandle,
    DbRole,
    ExecutionResult,
    PestScript,
    TargetEnv,
)
from app.models.enums import Outcome

# --- JUnit samples both runners emit (--log-junit) ---------------------------

# Pest writes file="<relpath>.php::<test name>".
_PEST_JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="Feature" tests="1" failures="0">
    <testcase name="happy path" classname="Tests\\Feature\\generated\\happy"
      file="tests/Feature/_generated/happy.php::happy path" time="0.10"/>
  </testsuite>
</testsuites>
"""

# PHPUnit nests testsuites, uses a bare file="<path>.php" (no ::suffix), a `class`
# attribute, and puts the failure message in the element text — all of which the
# shared parser already handles.
_PHPUNIT_JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="default">
    <testsuite name="Tests\\Feature\\_generated\\CheckoutTest"
      file="/app/tests/Feature/_generated/checkout.php" tests="1" failures="1">
      <testcase name="test_checkout_rejects_bad_discount"
        class="Tests\\Feature\\_generated\\CheckoutTest"
        classname="Tests.Feature._generated.CheckoutTest"
        file="/app/tests/Feature/_generated/checkout.php" line="12" time="0.05">
        <failure type="PHPUnit\\Framework\\ExpectationFailedException">Failed asserting that 201 matches expected 422.</failure>
      </testcase>
    </testsuite>
  </testsuite>
</testsuites>
"""


def _touch(app: Path, rel: str) -> None:
    path = app / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")


def _env(app: Path, evidence: Path) -> TargetEnv:
    return TargetEnv(
        app_path=str(app),
        execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
        evidence_dir=str(evidence),
    )


def _junit_writing_process(xml: str, recorder: list[list[str]]):
    """A spy Process that records argv and writes ``xml`` to the --log-junit path."""

    def process(
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout: float,
    ) -> ProcessResult:
        args = list(argv)
        recorder.append(args)
        junit_path = args[args.index("--log-junit") + 1]
        Path(junit_path).write_text(xml, encoding="utf-8")
        return ProcessResult(0, "ok", "")

    return process


# --- detection ---------------------------------------------------------------


def test_detects_pest_when_present(tmp_path: Path) -> None:
    _touch(tmp_path, "vendor/bin/pest")
    assert detect_test_binary(str(tmp_path)) == "vendor/bin/pest"


def test_detects_phpunit_when_only_phpunit_present(tmp_path: Path) -> None:
    _touch(tmp_path, "vendor/bin/phpunit")
    assert detect_test_binary(str(tmp_path)) == "vendor/bin/phpunit"


def test_prefers_pest_when_both_present(tmp_path: Path) -> None:
    _touch(tmp_path, "vendor/bin/pest")
    _touch(tmp_path, "vendor/bin/phpunit")
    assert detect_test_binary(str(tmp_path)) == "vendor/bin/pest"


def test_clear_error_when_neither_runner_exists(tmp_path: Path) -> None:
    with pytest.raises(RunnerProcessError) as exc:
        detect_test_binary(str(tmp_path))
    message = str(exc.value)
    assert "vendor/bin/pest" in message and "vendor/bin/phpunit" in message
    assert "composer install" in message  # actionable, not a raw FileNotFound


# --- run() uses the detected binary, parses both runners' JUnit ---------------


def test_run_uses_detected_pest_binary_and_maps_results(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _touch(app, "vendor/bin/pest")
    calls: list[list[str]] = []
    runner = PhpTestRunner(process=_junit_writing_process(_PEST_JUNIT, calls))
    script = PestScript(uuid.uuid4(), uuid.uuid4(), "happy", "<?php // generated")

    results = runner.run([script], _env(app, tmp_path / "ev"))

    assert calls[0][0].endswith("vendor/bin/pest")  # invoked Pest
    assert "--log-junit" in calls[0]
    assert results[0].name == "happy"
    assert results[0].outcome is Outcome.PASS


def test_run_uses_phpunit_when_that_is_what_the_target_has(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _touch(app, "vendor/bin/phpunit")  # NO pest — a vanilla-PHPUnit app
    calls: list[list[str]] = []
    runner = PhpTestRunner(process=_junit_writing_process(_PHPUNIT_JUNIT, calls))
    script = PestScript(uuid.uuid4(), uuid.uuid4(), "checkout", "<?php // generated")

    results = runner.run([script], _env(app, tmp_path / "ev"))

    assert calls[0][0].endswith("vendor/bin/phpunit")  # invoked PHPUnit
    assert results[0].name == "checkout"
    assert results[0].outcome is Outcome.FAIL  # the PHPUnit XML carries a <failure>
    assert "Failed asserting" in (results[0].message or "")


def test_run_fails_clearly_and_writes_no_files_when_no_runner(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()  # exists, but ships neither pest nor phpunit
    calls: list[list[str]] = []

    def spy(
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout: float,
    ) -> ProcessResult:
        calls.append(list(argv))
        return ProcessResult(0, "", "")

    runner = PhpTestRunner(process=spy)
    script = PestScript(uuid.uuid4(), uuid.uuid4(), "x", "<?php")

    with pytest.raises(RunnerProcessError, match="composer install"):
        runner.run([script], _env(app, tmp_path / "ev"))

    assert calls == []  # detected the gap → never spawned a process
    # Fail-fast: no generated files were written into the target.
    assert not (app / "tests" / "Feature" / "_generated").exists()


# --- JUnit shape (both runners) maps to the result shape lifecycle consumes ----


def test_phpunit_junit_parses_to_the_execution_result_shape(tmp_path: Path) -> None:
    cases = parse_junit(_PHPUNIT_JUNIT)
    script = PestScript(uuid.uuid4(), uuid.uuid4(), "checkout", "<?php")
    results = map_results([script], cases, evidence_ref="/ev/junit.xml")

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, ExecutionResult)  # exactly what RunLifecycle persists
    assert result.name == "checkout"  # mapped by file stem despite nested suites
    assert result.test_case_id == script.test_case_id
    assert result.outcome is Outcome.FAIL
    assert result.evidence_ref == "/ev/junit.xml"
