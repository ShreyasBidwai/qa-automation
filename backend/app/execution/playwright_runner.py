"""PlaywrightRunner — executes generated E2E specs against a running frontend.

Implements ExecutionRunner (TRD §5, ``framework="playwright"``), mirroring the
PestRunner (T1.5). It writes each generated ``.spec.ts`` into a throwaway
Playwright project, runs ``playwright test`` with JUnit + JSON reporting against
the target ``base_url``, parses per-test pass/fail/error from the JSON report,
and returns one ExecutionResult per script (evidence_ref → the captured
report/trace directory).

Safety + hygiene mirror the Pest runner: the dual-DB guard refuses any non-test
target up front (Architecture §9), and teardown removes the generated project on
success AND failure so no specs or browsers leak (Standards §11). Triage stays
null this sprint (Sprint 7). The browser never opens the DB itself; the target
app behind ``base_url`` must be test-backed.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.models.enums import Outcome

from .dual_db import ensure_safe_target
from .errors import MissingTargetUrlError
from .playwright_report import PlaywrightCase, parse_playwright_json
from .process import Process, run_process
from .types import ExecutionResult, PestScript, TargetEnv

# Generated Playwright projects are created UNDER the node project dir (so Node
# resolves @playwright/test up-tree) and removed wholesale on teardown.
_RUNS_DIRNAME = ".pw-runs"
_JUNIT_NAME = "playwright-junit.xml"
_JSON_NAME = "playwright-report.json"
_ARTIFACTS_NAME = "artifacts"  # traces / screenshots (Playwright outputDir)

# A throwaway Playwright config, parameterized entirely by env so the runner can
# point it at the target URL and the evidence paths. trace='on' captures a trace
# for every test (pass included) as evidence; retries=0 keeps it deterministic
# (Standards §15).
_CONFIG_TS = """\
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: false,
  retries: 0,
  timeout: 30000,
  expect: { timeout: 10000 },
  reporter: [
    ['list'],
    ['junit', { outputFile: process.env.PW_JUNIT }],
    ['json', { outputFile: process.env.PW_JSON }],
  ],
  outputDir: process.env.PW_OUTPUT_DIR,
  use: {
    baseURL: process.env.PW_BASE_URL,
    trace: 'on',
    screenshot: 'only-on-failure',
  },
});
"""


def _spec_stem(file: str) -> str:
    """The script name a spec file maps back to (``happy.spec.ts`` → ``happy``)."""
    name = Path(file).name
    for suffix in (".spec.ts", ".spec.js", ".ts", ".js"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _aggregate(outcomes: list[Outcome]) -> Outcome:
    # A real defect/crash dominates; then a verified pass; a set that is ONLY skips
    # (reachable-but-unverified, ADR-0064) aggregates to SKIPPED, not a silent pass.
    if Outcome.ERROR in outcomes:
        return Outcome.ERROR
    if Outcome.FAIL in outcomes:
        return Outcome.FAIL
    if Outcome.PASS in outcomes:
        return Outcome.PASS
    if Outcome.SKIPPED in outcomes:
        return Outcome.SKIPPED
    return Outcome.PASS


def map_results(
    scripts: list[PestScript],
    cases: list[PlaywrightCase],
    *,
    evidence_ref: str | None,
) -> list[ExecutionResult]:
    """Map Playwright cases back to their source scripts by spec-file stem.

    Mirrors the Pest runner: every input script gets exactly one result row; a
    script that produced no case (its spec never ran / never reported) becomes an
    ERROR, and multiple cases for one script take the worst outcome.
    """
    by_stem: dict[str, list[PlaywrightCase]] = {}
    for case in cases:
        by_stem.setdefault(_spec_stem(case.file), []).append(case)

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


class PlaywrightRunner:
    framework = "playwright"

    def __init__(
        self,
        *,
        node_project_dir: str = ".",
        process: Process = run_process,
        timeout: float = 300.0,
    ) -> None:
        # The dir that holds node_modules/@playwright/test (the runner image's
        # workdir). Generated projects live under it so Node resolves the package.
        self._node_project_dir = Path(node_project_dir).resolve()
        self._process = process
        self._timeout = timeout

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]:
        # Safety FIRST: refuse any non-test target environment (dual-DB guard).
        ensure_safe_target(target_env)
        if target_env.base_url is None:
            raise MissingTargetUrlError(
                "PlaywrightRunner requires TargetEnv.base_url (the target frontend)"
            )
        if not scripts:
            return []

        run_dir = self._node_project_dir / _RUNS_DIRNAME / uuid.uuid4().hex
        tests_dir = run_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        for script in scripts:
            (tests_dir / f"{script.name}.spec.ts").write_text(
                script.code, encoding="utf-8"
            )
        config_path = run_dir / "playwright.config.ts"
        config_path.write_text(_CONFIG_TS, encoding="utf-8")

        evidence_dir = Path(target_env.evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        junit_path = evidence_dir / _JUNIT_NAME
        json_path = evidence_dir / _JSON_NAME
        artifacts_dir = evidence_dir / _ARTIFACTS_NAME

        playwright_bin = self._node_project_dir / "node_modules" / ".bin" / "playwright"
        argv = [str(playwright_bin), "test", "--config", str(config_path)]
        proc_env = {
            "PW_BASE_URL": target_env.base_url,
            "PW_JUNIT": str(junit_path),
            "PW_JSON": str(json_path),
            "PW_OUTPUT_DIR": str(artifacts_dir),
            "CI": "1",  # disable Playwright's interactive/watch behaviors
        }
        result = self._process(argv, str(run_dir), proc_env, self._timeout)

        # Persist stdout/stderr alongside the structured reports as evidence.
        (evidence_dir / "playwright-stdout.log").write_text(
            f"{result.stdout}\n{result.stderr}", encoding="utf-8"
        )

        try:
            cases = parse_playwright_json(json_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # Playwright never wrote the report (e.g. it failed to start) → all
            # scripts become ERROR via map_results.
            cases = []
        return map_results(scripts, cases, evidence_ref=str(evidence_dir))

    def teardown(self, target_env: TargetEnv) -> None:
        """Remove generated Playwright projects so no specs leak (Standards §11).

        Idempotent — safe on completion and on failure. Browsers are spawned and
        reaped by the ``playwright test`` process itself; the captured evidence in
        ``evidence_dir`` is deliberately NOT removed.
        """
        shutil.rmtree(self._node_project_dir / _RUNS_DIRNAME, ignore_errors=True)
