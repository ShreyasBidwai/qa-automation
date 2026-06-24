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

import shutil
from pathlib import Path

from app.models.enums import Outcome

from .dual_db import ensure_safe_target, subprocess_db_env
from .errors import RunnerProcessError
from .junit import JUnitCase, parse_junit
from .process import Process, run_process
from .types import ExecutionResult, PestScript, TargetEnv

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
    raise RunnerProcessError(
        f"no PHP test runner found: neither {_PEST_BIN} nor {_PHPUNIT_BIN} exists "
        f"in {app_path} — run `composer install` in the target app"
    )


def _aggregate(outcomes: list[Outcome]) -> Outcome:
    if Outcome.ERROR in outcomes:
        return Outcome.ERROR
    if Outcome.FAIL in outcomes:
        return Outcome.FAIL
    return Outcome.PASS


def map_results(
    scripts: list[PestScript],
    cases: list[JUnitCase],
    *,
    evidence_ref: str | None,
) -> list[ExecutionResult]:
    """Map JUnit cases back to their source scripts by test-file stem.

    A script that produced no testcase (e.g. the runner crashed before running it)
    becomes an ERROR result — every input script gets exactly one result row.

    Runner-agnostic: Pest writes ``file="<relpath>.php::<test name>"`` while PHPUnit
    writes ``file="<path>.php"`` (no suffix); splitting on ``::`` and taking the file
    stem yields the script's unique name for both.
    """
    by_stem: dict[str, list[JUnitCase]] = {}
    for case in cases:
        if case.file:
            stem = Path(case.file.split("::", 1)[0]).stem
        else:
            stem = case.classname or case.name
        by_stem.setdefault(stem, []).append(case)

    results: list[ExecutionResult] = []
    for script in scripts:
        matched = by_stem.get(script.name, [])
        if not matched:
            results.append(
                ExecutionResult(
                    test_case_id=script.test_case_id,
                    script_id=script.script_id,
                    name=script.name,
                    outcome=Outcome.ERROR,
                    evidence_ref=evidence_ref,
                    message="no test result produced for script",
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
        # Pass explicit file paths (a bare directory yields "No tests found").
        rel_paths: list[str] = []
        for script in scripts:
            rel = Path(*_GENERATED) / f"{script.name}.php"
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

        try:
            cases = parse_junit(junit_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # The runner never wrote JUnit (e.g. fatal bootstrap error) → all ERROR.
            cases = []
        return map_results(scripts, cases, evidence_ref=str(junit_path))

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
