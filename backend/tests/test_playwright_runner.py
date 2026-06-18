"""PlaywrightRunner — fast backend tests (no real browser).

Canned Playwright JSON → ExecutionResult rows, the run wiring (specs written,
env wired, report parsed, evidence captured), the dual-DB / missing-URL guards,
and no-leak teardown — all with an injected fake process, so no browser ever
launches. The real-browser behaviour is the `e2e_runner` lane.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from app.execution.errors import (
    MissingTargetUrlError,
    PlaywrightReportError,
    ReadOnlyTargetError,
    RunnerTimeout,
)
from app.execution.playwright_report import PlaywrightCase, parse_playwright_json
from app.execution.playwright_runner import PlaywrightRunner, map_results
from app.execution.process import ProcessResult
from app.execution.types import DbHandle, DbRole, PestScript, TargetEnv
from app.models.enums import Outcome


def _script(name: str) -> PestScript:
    return PestScript(
        test_case_id=uuid.uuid4(),
        script_id=uuid.uuid4(),
        name=name,
        code="import { test, expect } from '@playwright/test';\n",
    )


def _target(
    tmp_path: Path, *, base_url: str | None = "http://127.0.0.1:9"
) -> TargetEnv:
    return TargetEnv(
        app_path=str(tmp_path),
        execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
        evidence_dir=str(tmp_path / "evidence"),
        base_url=base_url,
    )


def _report(specs: list[tuple[str, str, str | None]]) -> str:
    """A minimal Playwright JSON report: (file, result-status, error message)."""
    return json.dumps(
        {
            "suites": [
                {
                    "title": "tests",
                    "file": "tests",
                    "specs": [
                        {
                            "title": file,
                            "file": file,
                            "ok": status == "passed",
                            "tests": [
                                {
                                    "status": (
                                        "expected"
                                        if status == "passed"
                                        else "unexpected"
                                    ),
                                    "results": [
                                        {
                                            "status": status,
                                            "error": ({"message": msg} if msg else {}),
                                        }
                                    ],
                                }
                            ],
                        }
                        for (file, status, msg) in specs
                    ],
                }
            ]
        }
    )


def _fake_process(report: str | None, returncode: int = 0):
    """A Process spy that writes a canned report to PW_JSON (like `playwright`)."""

    def _run(
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout: float,
    ) -> ProcessResult:
        assert env is not None
        if report is not None:
            path = Path(env["PW_JSON"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report, encoding="utf-8")
        return ProcessResult(returncode, "stdout-log", "stderr-log")

    return _run


# --- report parsing ----------------------------------------------------------


def test_parse_maps_result_statuses_to_outcomes() -> None:
    report = _report(
        [
            ("p.spec.ts", "passed", None),
            ("f.spec.ts", "failed", "expected visible"),
            ("t.spec.ts", "timedOut", None),
            ("s.spec.ts", "skipped", None),
        ]
    )
    by_file = {c.file: c for c in parse_playwright_json(report)}
    assert by_file["p.spec.ts"].outcome is Outcome.PASS
    assert by_file["f.spec.ts"].outcome is Outcome.FAIL
    assert by_file["f.spec.ts"].message == "expected visible"
    assert by_file["t.spec.ts"].outcome is Outcome.ERROR  # did not complete
    assert by_file["s.spec.ts"].outcome is Outcome.ERROR  # did not run


def test_parse_recurses_nested_suites() -> None:
    report = json.dumps(
        {
            "suites": [
                {
                    "specs": [],
                    "suites": [
                        {
                            "specs": [
                                {
                                    "title": "n",
                                    "file": "n.spec.ts",
                                    "tests": [{"results": [{"status": "passed"}]}],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    )
    assert [c.file for c in parse_playwright_json(report)] == ["n.spec.ts"]


def test_parse_spec_without_results_is_error() -> None:
    report = json.dumps(
        {"suites": [{"specs": [{"title": "x", "file": "x.spec.ts", "tests": []}]}]}
    )
    assert parse_playwright_json(report)[0].outcome is Outcome.ERROR


def test_parse_malformed_report_raises() -> None:
    with pytest.raises(PlaywrightReportError):
        parse_playwright_json("{not json")


# --- result mapping ----------------------------------------------------------


def test_map_results_outcomes_and_evidence_ref() -> None:
    scripts = [_script("happy"), _script("missing")]
    cases = [
        PlaywrightCase("happy.spec.ts", "t", Outcome.PASS, None),
        PlaywrightCase("missing.spec.ts", "t", Outcome.FAIL, "boom"),
    ]
    results = map_results(scripts, cases, evidence_ref="/ev")
    by_name = {r.name: r for r in results}
    assert by_name["happy"].outcome is Outcome.PASS
    assert by_name["missing"].outcome is Outcome.FAIL
    assert by_name["missing"].message == "boom"
    assert by_name["happy"].test_case_id == scripts[0].test_case_id
    assert all(r.evidence_ref == "/ev" for r in results)


def test_map_results_script_without_case_becomes_error() -> None:
    results = map_results(
        [_script("ran"), _script("never")],
        [PlaywrightCase("ran.spec.ts", "t", Outcome.PASS, None)],
        evidence_ref=None,
    )
    by_name = {r.name: r for r in results}
    assert by_name["ran"].outcome is Outcome.PASS
    assert by_name["never"].outcome is Outcome.ERROR
    assert by_name["never"].message == "no test result produced for script"


def test_map_results_multiple_cases_take_worst_outcome() -> None:
    results = map_results(
        [_script("multi")],
        [
            PlaywrightCase("multi.spec.ts", "a", Outcome.PASS, None),
            PlaywrightCase("multi.spec.ts", "b", Outcome.FAIL, "assertion failed"),
        ],
        evidence_ref=None,
    )
    assert results[0].outcome is Outcome.FAIL
    assert results[0].message == "assertion failed"


# --- run wiring + guards + teardown -----------------------------------------


def test_run_writes_specs_wires_env_and_maps_results(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    scripts = [_script("happy"), _script("broken"), _script("never")]
    report = _report(
        [("happy.spec.ts", "passed", None), ("broken.spec.ts", "failed", "boom")]
    )
    runner = PlaywrightRunner(
        node_project_dir=str(proj), process=_fake_process(report, returncode=1)
    )

    results = runner.run(scripts, _target(tmp_path))

    by_name = {r.name: r for r in results}
    assert by_name["happy"].outcome is Outcome.PASS
    assert by_name["broken"].outcome is Outcome.FAIL
    assert by_name["broken"].message == "boom"
    assert by_name["never"].outcome is Outcome.ERROR  # no spec reported for it
    # Evidence: every result points at the evidence dir; reports/log are there.
    assert all(r.evidence_ref == str(tmp_path / "evidence") for r in results)
    assert (tmp_path / "evidence" / "playwright-report.json").exists()
    assert (tmp_path / "evidence" / "playwright-stdout.log").exists()
    # The generated specs were written into a throwaway project under the node dir.
    written = {p.name for p in (proj / ".pw-runs").glob("*/tests/*.spec.ts")}
    assert written == {"happy.spec.ts", "broken.spec.ts", "never.spec.ts"}


def test_run_requires_base_url(tmp_path: Path) -> None:
    runner = PlaywrightRunner(
        node_project_dir=str(tmp_path), process=_fake_process("{}")
    )
    with pytest.raises(MissingTargetUrlError):
        runner.run([_script("x")], _target(tmp_path, base_url=None))


def test_run_rejects_non_test_db(tmp_path: Path) -> None:
    runner = PlaywrightRunner(
        node_project_dir=str(tmp_path), process=_fake_process("{}")
    )
    env = TargetEnv(
        app_path=str(tmp_path),
        execution_db=DbHandle("postgresql://real", DbRole.READ_ONLY_REAL, False),
        evidence_dir=str(tmp_path / "evidence"),
        base_url="http://127.0.0.1:9",
    )
    with pytest.raises(ReadOnlyTargetError):
        runner.run([_script("x")], env)


def test_run_no_scripts_returns_empty(tmp_path: Path) -> None:
    runner = PlaywrightRunner(
        node_project_dir=str(tmp_path), process=_fake_process(None)
    )
    assert runner.run([], _target(tmp_path)) == []


def test_run_missing_report_marks_all_error(tmp_path: Path) -> None:
    # The process exits without ever writing the JSON report (e.g. failed to start).
    runner = PlaywrightRunner(
        node_project_dir=str(tmp_path / "proj"),
        process=_fake_process(None, returncode=1),
    )
    results = runner.run([_script("a"), _script("b")], _target(tmp_path))
    assert all(r.outcome is Outcome.ERROR for r in results)


def test_teardown_removes_generated_and_is_idempotent(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    runner = PlaywrightRunner(
        node_project_dir=str(proj),
        process=_fake_process(_report([("happy.spec.ts", "passed", None)])),
    )
    runner.run([_script("happy")], _target(tmp_path))
    assert (proj / ".pw-runs").exists()

    runner.teardown(_target(tmp_path))
    assert not (proj / ".pw-runs").exists()
    runner.teardown(_target(tmp_path))  # idempotent — safe to call again


def test_run_propagates_process_error_and_teardown_still_cleans(
    tmp_path: Path,
) -> None:
    proj = tmp_path / "proj"

    def _boom(
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout: float,
    ) -> ProcessResult:
        raise RunnerTimeout("playwright timed out")

    runner = PlaywrightRunner(node_project_dir=str(proj), process=_boom)
    with pytest.raises(RunnerTimeout):
        runner.run([_script("x")], _target(tmp_path))

    # The partial generated project is reclaimed by teardown — no leak (§11).
    runner.teardown(_target(tmp_path))
    assert not (proj / ".pw-runs").exists()
