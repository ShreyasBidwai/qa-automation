"""Run lifecycle — run row created, results persisted, status set, teardown run."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.errors import MissingTestRunnerError, RunnerProcessError
from app.execution.lifecycle import (
    STATUS_ERRORED,
    STATUS_FAILED,
    STATUS_PASSED,
    RunLifecycle,
)
from app.execution.types import (
    DbHandle,
    DbRole,
    ExecutionResult,
    PestScript,
    TargetEnv,
)
from app.models.enums import Outcome, RunMode, RunTrigger
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_test_case

_ENV = TargetEnv(
    app_path="/unused",
    execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
    evidence_dir="/unused",
)


class _FakeRunner:
    framework = "fake"

    def __init__(
        self,
        *,
        results: list[ExecutionResult] | None = None,
        boom: bool = False,
        missing: bool = False,
    ) -> None:
        self._results = results or []
        self._boom = boom
        self._missing = missing
        self.teardown_called = 0

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]:
        if self._missing:
            raise MissingTestRunnerError("no vendor/bin/pest in the target")
        if self._boom:
            raise RunnerProcessError("runner exploded")
        return self._results

    def teardown(self, target_env: TargetEnv) -> None:
        self.teardown_called += 1


async def _seed_cases(session: AsyncSession, project_id: uuid.UUID, n: int) -> list:
    repo = TestCaseRepository(session)
    return [await repo.add(make_test_case(project_id)) for _ in range(n)]


def _result(test_case_id: uuid.UUID, outcome: Outcome) -> ExecutionResult:
    return ExecutionResult(
        test_case_id=test_case_id,
        script_id=uuid.uuid4(),
        name=f"case-{test_case_id.hex[:6]}",
        outcome=outcome,
        evidence_ref="/ev/pest-junit.xml",
    )


async def test_lifecycle_persists_results_and_marks_passed(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    cases = await _seed_cases(db_session, project.id, 2)

    runner = _FakeRunner(results=[_result(c.id, Outcome.PASS) for c in cases])
    run = await RunLifecycle(runner=runner).execute(
        session=db_session,
        project_id=project.id,
        scripts=[],
        target_env=_ENV,
        trigger=RunTrigger.MANUAL,
        mode=RunMode.C,
        commit_sha="abc123",
    )

    assert run.status == STATUS_PASSED
    assert run.started_at is not None and run.finished_at is not None
    assert run.commit_sha == "abc123"
    assert run.run_number == 1  # friendly per-project number assigned at creation
    assert runner.teardown_called == 1

    rows = await ResultRepository(db_session).list_for_run(project.id, run.id)
    assert len(rows) == 2
    assert all(r.project_id == project.id and r.run_id == run.id for r in rows)
    assert all(r.triage is None for r in rows)  # triage deferred to Sprint 7
    assert all(r.evidence_ref == "/ev/pest-junit.xml" for r in rows)


async def test_lifecycle_marks_failed_when_a_test_fails(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    cases = await _seed_cases(db_session, project.id, 2)

    runner = _FakeRunner(
        results=[_result(cases[0].id, Outcome.PASS), _result(cases[1].id, Outcome.FAIL)]
    )
    run = await RunLifecycle(runner=runner).execute(
        session=db_session,
        project_id=project.id,
        scripts=[],
        target_env=_ENV,
        trigger=RunTrigger.CI,
        mode=RunMode.A,
    )

    assert run.status == STATUS_FAILED
    assert runner.teardown_called == 1
    rows = await ResultRepository(db_session).list_for_run(project.id, run.id)
    assert {r.outcome for r in rows} == {Outcome.PASS, Outcome.FAIL}


async def test_lifecycle_completes_as_failed_when_a_result_errored(
    db_session: AsyncSession,
) -> None:
    # An ERRORED result (a test that could not complete — e.g. an unparseable JUnit)
    # is non-passing, so the run reaches a NORMAL terminal status (FAILED) and is
    # persisted — it does NOT errored-out. The errored result survives as evidence.
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    cases = await _seed_cases(db_session, project.id, 2)

    runner = _FakeRunner(
        results=[
            _result(cases[0].id, Outcome.PASS),
            _result(cases[1].id, Outcome.ERROR),
        ]
    )
    run = await RunLifecycle(runner=runner).execute(
        session=db_session,
        project_id=project.id,
        scripts=[],
        target_env=_ENV,
        trigger=RunTrigger.CI,
        mode=RunMode.A,
    )

    assert run.status == STATUS_FAILED  # completed, NOT STATUS_ERRORED
    assert runner.teardown_called == 1
    rows = await ResultRepository(db_session).list_for_run(project.id, run.id)
    assert {r.outcome for r in rows} == {Outcome.PASS, Outcome.ERROR}


async def test_lifecycle_skips_api_layer_when_no_test_runner(
    db_session: AsyncSession,
) -> None:
    # No local composer-installed checkout (no vendor/bin/pest) → the API layer has
    # nothing runnable. The run must NOT error out; it SKIPS API execution (so the
    # caller can still run the UI crawl) and completes with zero results. Contrast
    # with a genuine runner crash below, which DOES error the run.
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    runner = _FakeRunner(missing=True)
    run = await RunLifecycle(runner=runner).execute(
        session=db_session,
        project_id=project.id,
        scripts=[],
        target_env=_ENV,
        trigger=RunTrigger.MANUAL,
        mode=RunMode.B,
    )

    assert run.status == STATUS_PASSED  # skipped, not errored — the run completes
    assert run.finished_at is not None
    assert runner.teardown_called == 1  # teardown still runs
    rows = await ResultRepository(db_session).list_for_run(project.id, run.id)
    assert rows == []  # nothing executed, so no results


async def test_lifecycle_errors_and_tears_down_on_runner_failure(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    runner = _FakeRunner(boom=True)
    with pytest.raises(RunnerProcessError):
        await RunLifecycle(runner=runner).execute(
            session=db_session,
            project_id=project.id,
            scripts=[],
            target_env=_ENV,
            trigger=RunTrigger.MANUAL,
            mode=RunMode.C,
        )

    # Teardown ran despite the failure (no leak), and the run is marked errored.
    assert runner.teardown_called == 1
    runs = await RunRepository(db_session).list(project.id)
    assert len(runs) == 1
    assert runs[0].status == STATUS_ERRORED
    assert runs[0].finished_at is not None
