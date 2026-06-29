"""Defensive JUnit result-parsing — a missing / empty / malformed JUnit file means a
test errored, hung, timed out, or crashed the runner (e.g. a RefreshDatabase test
against an unconfigured test DB). It is recorded as an ERRORED result carrying the
runner's captured stdout/stderr + exit code as the diagnostic, and the run CONTINUES;
it NEVER raises JUnitParseError and aborts the run. The valid-XML happy path is
unchanged. ERROR (execution/infra, inconclusive) is distinct from FAIL (a real defect).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.execution.php_test_runner import PhpTestRunner
from app.execution.process import ProcessResult
from app.execution.types import DbHandle, DbRole, PestScript, TargetEnv
from app.models.enums import Outcome

_BIN = "vendor/bin/phpunit"
# What a RefreshDatabase test against an unconfigured DB dumps to stdout/stderr.
_FATAL = (
    "PHP Fatal error: SQLSTATE[HY000] [2002] no such database; "
    "RefreshDatabase could not connect to the test database"
)


def _env(app: Path, evidence: Path) -> TargetEnv:
    return TargetEnv(
        app_path=str(app),
        execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
        evidence_dir=str(evidence),
    )


def _process(
    *, junit: str | None, stdout: str = "", stderr: str = "", returncode: int = 0
):
    """Spy Process: write ``junit`` to the --log-junit path (None → leave it MISSING),
    then return the captured output. No real PHPUnit runs."""

    def process(
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout: float,
    ) -> ProcessResult:
        if junit is not None:
            args = list(argv)
            path = args[args.index("--log-junit") + 1]
            Path(path).write_text(junit, encoding="utf-8")
        return ProcessResult(returncode, stdout, stderr)

    return process


def _script(name: str) -> PestScript:
    # No `class` in the code → the file stem is the sanitized slug (== name here),
    # which the JUnit ``file="…/<name>.php"`` matches.
    return PestScript(uuid.uuid4(), uuid.uuid4(), name, "<?php // generated")


def _valid_junit(stem: str, *, failure: bool = False) -> str:
    body = (
        "<failure>Failed asserting that 201 matches expected 422.</failure>"
        if (failure)
        else ""
    )
    case = (
        f'<testcase name="t" file="tests/Feature/_generated/{stem}.php">{body}'
        "</testcase>"
    )
    return (
        f'<?xml version="1.0"?><testsuites><testsuite>{case}</testsuite></testsuites>'
    )


def _run(tmp_path: Path, scripts: list[PestScript], **proc: object):
    app = tmp_path / "app"
    app.mkdir()
    runner = PhpTestRunner(process=_process(**proc), test_bin=_BIN)  # type: ignore[arg-type]
    return runner.run(scripts, _env(app, tmp_path / "ev"))


def test_empty_junit_file_is_an_errored_result_with_diagnostic(tmp_path: Path) -> None:
    results = _run(
        tmp_path, [_script("alpha")], junit="", stdout=_FATAL, returncode=255
    )
    assert len(results) == 1  # the run did NOT crash — it produced a result
    result = results[0]
    assert result.outcome is Outcome.ERROR  # inconclusive, NOT a FAIL
    assert "could not produce results" in (result.message or "")
    assert "exit 255" in result.message  # carries the runner's exit code
    assert "no such database" in result.message  # ...and its captured output


def test_missing_junit_file_is_an_errored_result(tmp_path: Path) -> None:
    results = _run(
        tmp_path, [_script("alpha")], junit=None, stderr=_FATAL, returncode=255
    )
    assert results[0].outcome is Outcome.ERROR
    assert "no such database" in (results[0].message or "")  # stderr captured too


def test_malformed_xml_is_an_errored_result_not_an_exception(tmp_path: Path) -> None:
    # Partial/garbage XML PHPUnit emits when a test dies mid-write. JUnitParseError is
    # caught, not raised — the run continues.
    results = _run(
        tmp_path,
        [_script("alpha")],
        junit="<testsuites><testcase ",
        stdout=_FATAL,
        returncode=1,
    )
    assert results[0].outcome is Outcome.ERROR
    assert "could not produce results" in (results[0].message or "")


def test_valid_junit_still_parses_exactly_as_before(tmp_path: Path) -> None:
    # Regression: a well-formed JUnit document parses to the normal outcome, and a
    # clean pass carries NO error diagnostic.
    results = _run(
        tmp_path, [_script("alpha")], junit=_valid_junit("alpha"), stdout="ok"
    )
    assert results[0].outcome is Outcome.PASS
    assert results[0].message is None


def test_mixed_batch_one_valid_one_errored(tmp_path: Path) -> None:
    # One script produced a (failing) testcase; the other produced none. Both are
    # handled, and the run completes with one normal FAIL + one ERROR result.
    results = _run(
        tmp_path,
        [_script("alpha"), _script("beta")],  # only alpha appears in the XML
        junit=_valid_junit("alpha", failure=True),
        stdout=_FATAL,
        returncode=1,
    )
    by_name = {r.name: r for r in results}
    assert len(results) == 2  # every input script got a result — the run continued
    assert by_name["alpha"].outcome is Outcome.FAIL  # a real asserted defect
    assert by_name["beta"].outcome is Outcome.ERROR  # could not complete
    assert "could not produce results" in (by_name["beta"].message or "")
