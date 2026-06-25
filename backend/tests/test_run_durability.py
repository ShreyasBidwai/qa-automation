"""Run durability — generated cases + the run row survive a mid-run crash.

The run row is persisted (committed, status=running) BEFORE generation, and each
generated case is committed per target — so a crash loses at most the in-flight
target, never the whole run's work (the b8bae544 incident: ~30 cases rolled back).
A crashed run is reconciled from 'running' to 'interrupted' (compare-and-set, so a
run that legitimately finished is never clobbered). The never-clobber reuse path
lets a re-run resume from the cases already committed.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.lifecycle import (
    STATUS_INTERRUPTED,
    STATUS_PASSED,
    STATUS_RUNNING,
    RunLifecycle,
)
from app.execution.types import PestScript
from app.models.enums import NodeKind, Outcome, RunMode, RunTrigger
from app.models.test_case import TestCase
from app.modes.mode_b import ModeBBounds
from app.modes.selection import SelectionStrategyKind, Target, build_selection_strategy
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository
from tests.factories import make_test_case, make_test_script
from tests.test_mode_b import (
    _node,
    _orchestrator,
    _project,
    _StubGenerator,
    _StubRunner,
)


async def _count_cases(session: AsyncSession, project_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(TestCase)
            .where(TestCase.project_id == project_id)
        )
        or 0
    )


def _full_sweep(session: AsyncSession):
    return build_selection_strategy(SelectionStrategyKind.FULL_SWEEP, session=session)


class _CrashingGenerator:
    """Generates a real case+script per target, then RAISES on the Nth call —
    a mid-run crash (e.g. a DB outage) after some cases were already produced."""

    def __init__(self, session: AsyncSession, *, crash_on_call: int) -> None:
        self._session = session
        self._crash_on = crash_on_call
        self._calls = 0
        self.generated_for: list[uuid.UUID] = []

    async def generate(self, *, project_id: uuid.UUID, target: Target) -> PestScript:
        self._calls += 1
        if self._calls >= self._crash_on:
            raise RuntimeError("simulated mid-run crash (e.g. DB outage)")
        case = await TestCaseRepository(self._session).add(
            make_test_case(project_id, target_node=target.node_id)
        )
        script = await TestScriptRepository(self._session).add(
            make_test_script(project_id, case.id)
        )
        self.generated_for.append(target.node_id)
        return PestScript(
            test_case_id=case.id,
            script_id=script.id,
            name=f"gen-{target.node_id.hex[:8]}",
            code=script.code,
        )


async def test_run_row_is_persisted_at_start_before_generation(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    lifecycle = RunLifecycle(runner=_StubRunner())

    run = await lifecycle.start(
        session=db_session, project_id=pid, trigger=RunTrigger.CI, mode=RunMode.B
    )

    # A real, COMMITTED row exists the instant start() returns — before any case is
    # generated — so a later crash can never roll the whole run back to nothing.
    assert run.status == STATUS_RUNNING
    assert run.started_at is not None and run.finished_at is None
    assert run.run_number == 1
    fetched = await RunRepository(db_session).get(pid, run.id)
    assert fetched is not None and fetched.status == STATUS_RUNNING
    assert await _count_cases(db_session, pid) == 0  # nothing generated yet


async def test_crash_mid_generation_keeps_committed_cases_and_run_row(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    for i in range(4):
        await _node(db_session, pid, NodeKind.ENDPOINT, f"GET api/r{i}")

    gen = _CrashingGenerator(db_session, crash_on_call=3)  # crash on target 3 of 4
    orchestrator = _orchestrator(db_session, gen, _StubRunner(Outcome.FAIL))

    with pytest.raises(RuntimeError, match="simulated mid-run crash"):
        await orchestrator.run(
            project_id=pid,
            strategy=_full_sweep(db_session),
            bounds=ModeBBounds(max_targets=10),
        )

    # The run row was committed at START → it survives the crash (NOT rolled back).
    runs = await RunRepository(db_session).list_for_project(pid, limit=10, offset=0)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == STATUS_RUNNING  # orphaned, awaiting reconcile

    # Exactly the 2 cases generated before the crash are durable — partial, not lost.
    assert await _count_cases(db_session, pid) == 2
    assert len(gen.generated_for) == 2

    # The worker's reconcile flips the orphaned run to 'interrupted' (compare-and-set).
    assert await RunRepository(db_session).mark_interrupted(run.id) is True
    await db_session.refresh(run)
    assert run.status == STATUS_INTERRUPTED


async def test_rerun_after_partial_reuses_committed_cases_and_continues(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    for i in range(4):
        await _node(db_session, pid, NodeKind.ENDPOINT, f"GET api/r{i}")

    # A partial run crashes after 2 targets → 2 cases durably committed.
    with pytest.raises(RuntimeError):
        await _orchestrator(
            db_session, _CrashingGenerator(db_session, crash_on_call=3), _StubRunner()
        ).run(
            project_id=pid,
            strategy=_full_sweep(db_session),
            bounds=ModeBBounds(max_targets=10),
        )
    assert await _count_cases(db_session, pid) == 2

    # A re-run REUSES the 2 committed cases (never regenerates them) and generates
    # only the 2 not-yet-covered targets — incremental-persist gives free resume.
    gen = _StubGenerator(db_session)
    report = await _orchestrator(db_session, gen, _StubRunner(Outcome.PASS)).run(
        project_id=pid,
        strategy=_full_sweep(db_session),
        bounds=ModeBBounds(max_targets=10),
    )

    assert report.cases_reused == 2
    assert report.cases_generated == 2
    assert len(gen.generated_for) == 2  # only the uncovered targets were generated
    assert await _count_cases(db_session, pid) == 4


async def test_mark_interrupted_is_compare_and_set(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    lifecycle = RunLifecycle(runner=_StubRunner())
    runs = RunRepository(db_session)

    # A still-running run is reconciled.
    running = await lifecycle.start(
        session=db_session, project_id=pid, trigger=RunTrigger.CI, mode=RunMode.B
    )
    assert await runs.mark_interrupted(running.id) is True
    await db_session.refresh(running)
    assert running.status == STATUS_INTERRUPTED

    # A run that legitimately finished is NEVER clobbered (CAS on 'running').
    finished = await lifecycle.start(
        session=db_session, project_id=pid, trigger=RunTrigger.CI, mode=RunMode.B
    )
    finished.status = STATUS_PASSED
    await db_session.flush()
    assert await runs.mark_interrupted(finished.id) is False
    await db_session.refresh(finished)
    assert finished.status == STATUS_PASSED


async def test_interrupt_stale_running_sweep_reconciles_only_running(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    lifecycle = RunLifecycle(runner=_StubRunner())
    runs = RunRepository(db_session)

    stale = await lifecycle.start(
        session=db_session, project_id=pid, trigger=RunTrigger.CI, mode=RunMode.B
    )
    done = await lifecycle.start(
        session=db_session, project_id=pid, trigger=RunTrigger.CI, mode=RunMode.B
    )
    done.status = STATUS_PASSED
    await db_session.flush()

    swept = await runs.interrupt_stale_running()  # the worker's startup sweep

    assert stale.id in swept and done.id not in swept
    await db_session.refresh(stale)
    await db_session.refresh(done)
    assert stale.status == STATUS_INTERRUPTED
    assert done.status == STATUS_PASSED
