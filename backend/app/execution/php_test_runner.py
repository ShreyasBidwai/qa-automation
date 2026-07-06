"""PhpTestRunner — executes generated PHP test scripts against a bootable Laravel app.

Implements ExecutionRunner (TRD §5). The target app may ship EITHER test runner —
Pest (``vendor/bin/pest``) or vanilla PHPUnit (``vendor/bin/phpunit``); Pest is
common but not universal. The runner DETECTS whichever the target actually has
(Pest preferred, else PHPUnit) and invokes it the same way: both accept explicit
file paths plus ``--log-junit <file>`` and emit standard JUnit XML, so result
parsing (junit.py) is runner-agnostic. If the target has neither binary, the run
fails with a clear, honest error rather than a raw "executable not found".

It writes each script into the app's ``tests/Feature/_generated/`` directory, runs
the detected binary with JUnit output against the writable test DB, parses per-test
pass/fail/error, and returns one ExecutionResult per script (evidence_ref → the
captured JUnit artifact). The runner never touches the control-plane DB and never
executes against a non-test DB (dual_db guard).
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from app.models.enums import Outcome

from .dual_db import ensure_safe_target, subprocess_db_env
from .errors import JUnitParseError, MissingTestRunnerError
from .junit import JUnitCase, parse_junit
from .process import Process, ProcessResult, run_process
from .types import ExecutionResult, PestScript, TargetEnv

logger = logging.getLogger("app.execution")

_GENERATED = ("tests", "Feature", "_generated")

# Candidate test binaries, in preference order. Pest is preferred where present
# (it is a superset — it also runs PHPUnit-style test classes); a target without
# Pest falls back to vanilla PHPUnit. Both accept ``--log-junit`` + file paths.
_PEST_BIN = "vendor/bin/pest"
_PHPUNIT_BIN = "vendor/bin/phpunit"


def detect_test_binary(app_path: str) -> str:
    """The target's PHP test binary (repo-relative) — Pest preferred, else PHPUnit.

    Raises ``RunnerProcessError`` with a clear, actionable message when neither is
    installed (rather than letting the process layer surface a raw FileNotFound on
    a hard-coded path). Project-agnostic: only the binary path differs between the
    two runners; the invocation is identical.
    """
    app = Path(app_path)
    for rel in (_PEST_BIN, _PHPUNIT_BIN):
        if (app / rel).exists():
            return rel
    raise MissingTestRunnerError(
        f"no PHP test runner found: neither {_PEST_BIN} nor {_PHPUNIT_BIN} exists "
        f"in {app_path} — run `composer install` in the target app"
    )


def _test_identifier(script: PestScript) -> str:
    """The file stem to write a script under (== its PHP test class name).

    PHPUnit, when handed a file directly, requires the declared class to MATCH the
    file basename (``Foo.php`` ⇒ ``class Foo``) — so we name the file after the class
    the generator emitted. Pest is lenient (it just includes the file), so this is
    safe for both. A script that declares no class (a hand-written Pest closure
    script) falls back to a sanitized version of its slug.
    """
    match = re.search(r"\bclass\s+(\w+)", script.code)
    if match:
        return match.group(1)
    ident = re.sub(r"\W+", "_", script.name).strip("_") or "GeneratedTest"
    if ident[0].isdigit():
        ident = f"t_{ident}"
    return ident


def _aggregate(outcomes: list[Outcome]) -> Outcome:
    # A real defect/crash dominates; then a verified pass; a script whose cases are ALL
    # skipped (reachable-but-unverified, ADR-0064) is itself SKIPPED, NOT a silent pass
    # — else a skip would wrongly count toward pass-rate and seed a heal candidate.
    if Outcome.ERROR in outcomes:
        return Outcome.ERROR
    if Outcome.FAIL in outcomes:
        return Outcome.FAIL
    if Outcome.PASS in outcomes:
        return Outcome.PASS
    if Outcome.SKIPPED in outcomes:
        return Outcome.SKIPPED
    return Outcome.PASS


# Cap the diagnostic copied onto an errored result's message — the runner's full
# stdout/stderr is persisted to evidence (test-stdout.log); the result carries the
# tail (where a PHP fatal / "Expected 200, got 500" lands), not megabytes.
_DIAGNOSTIC_TAIL = 2000


def _execution_error_detail(result: ProcessResult) -> str:
    """A diagnostic for a script that produced NO test result — an execution/infra
    error ("test could not complete"), NOT a real test failure. Carries the runner's
    exit code + the tail of its captured output so the errored finding is useful."""
    output = result.stdout
    if result.stderr.strip():
        output = f"{output}\n{result.stderr}" if output else result.stderr
    output = output.strip()
    tail = output[-_DIAGNOSTIC_TAIL:] if output else "(no output captured)"
    return (
        "test errored — could not produce results "
        f"(runner exit {result.returncode}); see captured output:\n{tail}"
    )


def map_results(
    scripts: list[PestScript],
    cases: list[JUnitCase],
    *,
    evidence_ref: str | None,
    error_detail: str | None = None,
) -> list[ExecutionResult]:
    """Map JUnit cases back to their source scripts by test-file stem.

    A script that produced no testcase (e.g. the runner crashed before running it, or
    the JUnit file was missing/empty/malformed) becomes an ERROR result — every input
    script gets exactly one result row. ``error_detail`` (the runner's captured
    output) is attached as that ERROR result's message when present, so an execution
    error carries a useful diagnostic instead of a bare placeholder.

    Runner-agnostic: a script is identified by its test CLASS name (the file
    basename we wrote). A ``<testcase>`` is matched to it by EITHER the file stem
    (PHPUnit emits ``file="<Class>.php"``) OR the class short-name — Pest mangles the
    ``file`` attribute and reports a dotted ``classname`` (``Tests.Feature.<Class>``),
    so we also key on the last FQCN segment. Both runners map back to the script.
    """
    by_key: dict[str, list[JUnitCase]] = {}
    for case in cases:
        keys: set[str] = set()
        if case.file:
            keys.add(Path(case.file.split("::", 1)[0]).stem)
        if case.classname:
            # PHPUnit separates the FQCN with "\\"; Pest's JUnit uses "." — take the
            # last segment (the class short-name) for either.
            keys.add(re.split(r"[\\.]", case.classname)[-1])
        if not keys:
            keys.add(case.name)
        for key in keys:
            by_key.setdefault(key, []).append(case)

    results: list[ExecutionResult] = []
    for script in scripts:
        matched = by_key.get(_test_identifier(script), [])
        if not matched:
            results.append(
                ExecutionResult(
                    test_case_id=script.test_case_id,
                    script_id=script.script_id,
                    name=script.name,
                    outcome=Outcome.ERROR,
                    evidence_ref=evidence_ref,
                    message=error_detail or "no test result produced for script",
                )
            )
            continue
        outcome = _aggregate([c.outcome for c in matched])
        message = next(
            (c.message for c in matched if c.outcome is not Outcome.PASS), None
        )
        results.append(
            ExecutionResult(
                test_case_id=script.test_case_id,
                script_id=script.script_id,
                name=script.name,
                outcome=outcome,
                evidence_ref=evidence_ref,
                message=message,
            )
        )
    return results


class PhpTestRunner:
    # Registry key (ADR-0054 maps the laravel stack → this runner). The runner
    # serves both Pest and PHPUnit targets; the binary is detected per run.
    framework = "pest"

    def __init__(
        self,
        *,
        process: Process = run_process,
        test_bin: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._process = process
        # An explicit binary override (repo-relative) skips detection; ``None`` →
        # detect Pest/PHPUnit from the target at run time.
        self._test_bin = test_bin
        self._timeout = timeout

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]:
        # Dual-DB guard FIRST: refuse to proceed against anything but the test DB.
        ensure_safe_target(target_env)
        if not scripts:
            return []

        app = Path(target_env.app_path)
        # Detect the runner BEFORE writing any files — fail fast and clearly if the
        # target ships neither Pest nor PHPUnit.
        test_bin = self._test_bin or detect_test_binary(target_env.app_path)

        gen_dir = app.joinpath(*_GENERATED)
        gen_dir.mkdir(parents=True, exist_ok=True)
        # Pass explicit file paths (a bare directory yields "No tests found"). Each
        # file is named after the test CLASS it declares — PHPUnit requires
        # class-name == file-basename when a file is run directly (Pest is lenient).
        rel_paths: list[str] = []
        for script in scripts:
            rel = Path(*_GENERATED) / f"{_test_identifier(script)}.php"
            (app / rel).write_text(script.code, encoding="utf-8")
            rel_paths.append(str(rel))

        evidence_dir = Path(target_env.evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        junit_path = evidence_dir / "junit.xml"

        argv = [
            str(app / test_bin),
            "--log-junit",
            str(junit_path),
            *rel_paths,
        ]
        proc_env = subprocess_db_env(target_env.execution_db)
        result = self._process(argv, str(app), proc_env, self._timeout)

        # Persist stdout/stderr alongside the JUnit artifact as evidence.
        (evidence_dir / "test-stdout.log").write_text(
            f"{result.stdout}\n{result.stderr}", encoding="utf-8"
        )

        # Defensive result-parsing (run-resilience): a MISSING, EMPTY, or MALFORMED
        # JUnit file means PHPUnit/Pest could not produce results for (some of) the
        # scripts — a test errored, hung, timed out, or crashed the runner (e.g. a
        # RefreshDatabase test against an unconfigured test DB). NEVER abort the run on
        # that: parse whatever is there, and every script with no testcase becomes an
        # ERROR result carrying the runner's captured output as the diagnostic. A VALID
        # file still parses exactly as before (the happy path is unchanged).
        try:
            xml = junit_path.read_text(encoding="utf-8")
            cases = parse_junit(xml) if xml.strip() else []
        except FileNotFoundError:
            cases = []  # the runner never wrote JUnit (fatal/crash) → all ERROR below
        except JUnitParseError:
            logger.warning(
                "execution.junit_unparsable",
                extra={"junit": str(junit_path), "returncode": result.returncode},
            )
            cases = []  # empty/malformed XML → unmatched scripts become ERROR below
        # The runner's captured output is the diagnostic for ANY script that produced
        # no testcase — a whole-file failure OR a partial JUnit that omitted it.
        return map_results(
            scripts,
            cases,
            evidence_ref=str(junit_path),
            error_detail=_execution_error_detail(result),
        )

    def teardown(self, target_env: TargetEnv) -> None:
        """Remove generated test files so no app state leaks (Standards §11).

        Idempotent — safe to call on completion and on failure. The test DB is
        sqlite in-memory and dies with the runner process, so there is nothing
        else to reclaim.
        """
        gen_dir = Path(target_env.app_path).joinpath(*_GENERATED)
        shutil.rmtree(gen_dir, ignore_errors=True)


# Backward-compatible alias — the runner was historically Pest-only (``PestRunner``).
# It now detects Pest OR PHPUnit; the old name still resolves for any caller/test.
PestRunner = PhpTestRunner
