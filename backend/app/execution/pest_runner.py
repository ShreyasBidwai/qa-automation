"""PestRunner — executes generated Pest scripts against a bootable Laravel app.

Implements ExecutionRunner (TRD §5, ``framework="pest"``). It writes each script
into the app's ``tests/Feature/_generated/`` directory, runs Pest with JUnit
output against the writable test DB, parses per-test pass/fail/error, and returns
one ExecutionResult per script (evidence_ref → the captured JUnit artifact).

Triage stays null this sprint (Sprint 7). The runner never touches the
control-plane DB and never executes against a non-test DB (dual_db guard).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.models.enums import Outcome

from .dual_db import ensure_safe_target, subprocess_db_env
from .junit import JUnitCase, parse_junit
from .process import Process, run_process
from .types import ExecutionResult, PestScript, TargetEnv

_GENERATED = ("tests", "Feature", "_generated")


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

    A script that produced no testcase (e.g. Pest crashed before running it)
    becomes an ERROR result — every input script gets exactly one result row.
    """
    by_stem: dict[str, list[JUnitCase]] = {}
    for case in cases:
        # Pest writes file="<relpath>.php::<test name>" — split off the suffix
        # and take the file stem (the script's unique name).
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


class PestRunner:
    framework = "pest"

    def __init__(
        self,
        *,
        process: Process = run_process,
        pest_bin: str = "vendor/bin/pest",
        timeout: float = 300.0,
    ) -> None:
        self._process = process
        self._pest_bin = pest_bin
        self._timeout = timeout

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]:
        # Dual-DB guard FIRST: refuse to proceed against anything but the test DB.
        ensure_safe_target(target_env)
        if not scripts:
            return []

        app = Path(target_env.app_path)
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
        junit_path = evidence_dir / "pest-junit.xml"

        argv = [
            str(app / self._pest_bin),
            "--log-junit",
            str(junit_path),
            *rel_paths,
        ]
        proc_env = subprocess_db_env(target_env.execution_db)
        result = self._process(argv, str(app), proc_env, self._timeout)

        # Persist stdout/stderr alongside the JUnit artifact as evidence.
        (evidence_dir / "pest-stdout.log").write_text(
            f"{result.stdout}\n{result.stderr}", encoding="utf-8"
        )

        try:
            cases = parse_junit(junit_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # Pest never wrote JUnit (e.g. fatal bootstrap error) → all ERROR.
            cases = []
        return map_results(scripts, cases, evidence_ref=str(junit_path))

    def teardown(self, target_env: TargetEnv) -> None:
        """Remove generated test files so no app state leaks (Standards §11).

        Idempotent — safe to call on completion and on failure. The test DB is
        sqlite in-memory and dies with the Pest process, so there is nothing
        else to reclaim.
        """
        gen_dir = Path(target_env.app_path).joinpath(*_GENERATED)
        shutil.rmtree(gen_dir, ignore_errors=True)
