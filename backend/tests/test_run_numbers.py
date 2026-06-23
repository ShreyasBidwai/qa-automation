"""Payload enrichment (ADR-0048): friendly run number + per-run severity breakdown.

The friendly per-project run number — atomic, sequential, per-project, stable,
concurrency-safe — plus the deterministic backfill, and the batched per-run
open-findings severity breakdown. Tested at the repo/reader level with full control
over runs/findings/triage; the API wiring (RunListItem / run status / finding payload)
is covered in test_api_lists.py + test_api.py, and the lifecycle assignment in
test_execution_lifecycle.py.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.enums import FindingLayer, OracleSource, Outcome, TriageStatus
from app.models.finding import SEVERITY_UNSET, Finding
from app.models.project import Project
from app.models.run import Run
from app.reporting.open_findings import OpenFindingsReader
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


async def _project(session: AsyncSession) -> uuid.UUID:
    return (await ProjectRepository(session).add(make_project())).id


# --- friendly run number: assignment, per-project, stability -----------------


async def test_next_run_number_is_sequential_from_one(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    repo = RunRepository(db_session)
    assert [await repo.next_run_number(pid) for _ in range(3)] == [1, 2, 3]


async def test_run_number_sequence_is_per_project(db_session: AsyncSession) -> None:
    repo = RunRepository(db_session)
    a = await _project(db_session)
    b = await _project(db_session)
    # Interleaved claims: each project advances its OWN counter, both from 1.
    assert await repo.next_run_number(a) == 1
    assert await repo.next_run_number(a) == 2
    assert await repo.next_run_number(b) == 1
    assert await repo.next_run_number(a) == 3
    assert await repo.next_run_number(b) == 2


async def test_next_run_number_unknown_project_raises(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await RunRepository(db_session).next_run_number(uuid.uuid4())


async def test_run_number_is_stable_as_later_runs_are_numbered(
    db_session: AsyncSession,
) -> None:
    """Once claimed, a run's number never moves — later runs take later numbers."""
    pid = await _project(db_session)
    repo = RunRepository(db_session)
    first = await repo.add(make_run(pid, run_number=await repo.next_run_number(pid)))
    first_id = first.id
    for _ in range(3):  # three more runs claim 2, 3, 4
        await repo.add(make_run(pid, run_number=await repo.next_run_number(pid)))

    db_session.expire_all()
    reloaded = await repo.get(pid, first_id)
    assert reloaded is not None and reloaded.run_number == 1


# --- concurrency safety (committing sessionmaker) ----------------------------


@pytest_asyncio.fixture
async def sessionmaker_(
    test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A committing sessionmaker for true-concurrency tests (own connections)."""
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _committed_project(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with maker() as session:
        project = make_project()
        session.add(project)
        await session.flush()
        pid = project.id
        await session.commit()
        return pid


async def _cleanup_project(
    maker: async_sessionmaker[AsyncSession], pid: uuid.UUID
) -> None:
    async with maker() as session:
        await session.execute(delete(Run).where(Run.project_id == pid))
        await session.execute(delete(Project).where(Project.id == pid))
        await session.commit()


async def test_parallel_run_creation_never_duplicates_numbers(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """Concurrency-safe: N parallel run creations each on their own connection
    serialize on the project-row lock → distinct, contiguous numbers. The
    ``(project_id, run_number)`` unique index is the backstop (a dup would raise
    on commit). ADR-0048."""
    pid = await _committed_project(sessionmaker_)
    try:

        async def create_run() -> int:
            async with sessionmaker_() as session:
                repo = RunRepository(session)
                number = await repo.next_run_number(pid)
                await repo.add(make_run(pid, run_number=number, created_at=_BASE))
                await session.commit()
                return number

        numbers = await asyncio.gather(*(create_run() for _ in range(12)))
        assert sorted(numbers) == list(range(1, 13))  # distinct + no gaps

        async with sessionmaker_() as session:
            rows = await session.execute(
                select(Run.run_number).where(Run.project_id == pid)
            )
            persisted = [n for n in rows.scalars().all() if n is not None]
        assert sorted(persisted) == list(range(1, 13))
    finally:
        await _cleanup_project(sessionmaker_, pid)


# --- deterministic backfill (mirrors migration 0027) -------------------------


async def test_backfill_numbers_runs_deterministically_by_created_at(
    db_session: AsyncSession,
) -> None:
    """The migration's backfill: number a project's runs 1..N ordered by
    (created_at, id) — deterministic regardless of insert order. This runs the
    exact ROW_NUMBER step from migration 0027 (scoped to the seeded project)."""
    pid = await _project(db_session)
    repo = RunRepository(db_session)
    # Insert out of chronological order; numbers are NULL pre-backfill (additive).
    r_c = await repo.add(make_run(pid, created_at=_BASE + timedelta(hours=3)))
    r_a = await repo.add(make_run(pid, created_at=_BASE + timedelta(hours=1)))
    r_b = await repo.add(make_run(pid, created_at=_BASE + timedelta(hours=2)))
    ids = {r_a.id: 1, r_b.id: 2, r_c.id: 3}  # expected number by chronological order
    assert all(r.run_number is None for r in (r_a, r_b, r_c))

    await db_session.execute(
        text(
            """
            WITH numbered AS (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY project_id ORDER BY created_at, id
                ) AS rn
                FROM runs WHERE project_id = :pid
            )
            UPDATE runs SET run_number = numbered.rn
            FROM numbered WHERE runs.id = numbered.id
            """
        ),
        {"pid": pid},
    )

    # Read the assigned numbers straight from the columns (fresh, not the ORM cache).
    rows = await db_session.execute(
        select(Run.id, Run.run_number).where(Run.project_id == pid)
    )
    assert {row.id: row.run_number for row in rows} == ids


# --- per-run severity breakdown ----------------------------------------------


async def _seed_finding(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    key: str,
    severity: str = "major",
    triage: TriageStatus | None = None,
) -> Finding:
    case = await TestCaseRepository(session).add(make_test_case(project_id))
    result = await ResultRepository(session).add(
        make_result(project_id, run_id, case.id, outcome=Outcome.FAIL)
    )
    finding = await FindingRepository(session).add(
        Finding(
            project_id=project_id,
            run_id=run_id,
            result_id=result.id,
            root_cause_key=key,
            explains_count=1,
            title=f"finding {key}",
            layer=FindingLayer.API,
            oracle_source=OracleSource.RULE_DERIVED,
            confidence_mixed=False,
            expected={},
            location={},
            severity=severity,
            status="new",
        )
    )
    if triage is not None:
        await FindingTriageRepository(session).upsert(
            project_id, key, status=triage, note=None
        )
    return finding


async def test_severity_counts_group_by_run_and_tier(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    repo = RunRepository(db_session)
    run1 = await repo.add(make_run(pid, created_at=_BASE))
    run2 = await repo.add(make_run(pid, created_at=_BASE + timedelta(hours=1)))
    await _seed_finding(db_session, pid, run1.id, key="c1", severity="critical")
    await _seed_finding(db_session, pid, run1.id, key="m1", severity="major")
    await _seed_finding(db_session, pid, run1.id, key="m2", severity="major")
    await _seed_finding(db_session, pid, run1.id, key="n1", severity="minor")
    await _seed_finding(db_session, pid, run2.id, key="c2", severity="critical")

    counts = await OpenFindingsReader(db_session).severity_counts_by_run(
        [run1.id, run2.id]
    )
    assert counts[run1.id] == {"critical": 1, "major": 2, "minor": 1}
    assert counts[run2.id] == {"critical": 1}


async def test_severity_counts_exclude_muted_and_unset(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    run = await RunRepository(db_session).add(make_run(pid, created_at=_BASE))
    await _seed_finding(db_session, pid, run.id, key="open", severity="critical")
    # Resolved is muted (out of "currently open"); unset is unscored (not a tier).
    await _seed_finding(
        db_session, pid, run.id, key="done", severity="major",
        triage=TriageStatus.RESOLVED,
    )
    await _seed_finding(db_session, pid, run.id, key="raw", severity=SEVERITY_UNSET)

    counts = await OpenFindingsReader(db_session).severity_counts_by_run([run.id])
    assert counts[run.id] == {"critical": 1}


async def test_severity_counts_run_with_no_open_findings_is_absent(
    db_session: AsyncSession,
) -> None:
    """A run with no open findings is absent from the map → the API renders zeros
    via SeverityBreakdown's defaults."""
    pid = await _project(db_session)
    run = await RunRepository(db_session).add(make_run(pid, created_at=_BASE))
    counts = await OpenFindingsReader(db_session).severity_counts_by_run([run.id])
    assert run.id not in counts
    assert counts == {}


@pytest_asyncio.fixture
async def counting_session(
    test_database_url: str,
) -> AsyncIterator[tuple[AsyncSession, list[int]]]:
    """A rolled-back session plus a live SQL statement counter (for N+1 checks)."""
    engine = create_async_engine(test_database_url)
    calls: list[int] = []

    def _count(*_args: object) -> None:
        calls.append(1)

    event.listen(engine.sync_engine, "before_cursor_execute", _count)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session, calls
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _count)
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def test_severity_counts_are_batched_no_n_plus_one(
    counting_session: tuple[AsyncSession, list[int]],
) -> None:
    """The breakdown is one batched aggregation across the page of runs — the
    statement count does NOT grow with the number of runs (no per-run query)."""
    session, calls = counting_session
    pid = await _project(session)
    repo = RunRepository(session)
    run_ids: list[uuid.UUID] = []
    for hour in range(6):
        run = await repo.add(make_run(pid, created_at=_BASE + timedelta(hours=hour)))
        await _seed_finding(session, pid, run.id, key=f"k{hour}", severity="major")
        run_ids.append(run.id)

    reader = OpenFindingsReader(session)
    calls.clear()
    counts = await reader.severity_counts_by_run(run_ids)

    assert sum(bucket.get("major", 0) for bucket in counts.values()) == 6
    # findings read + triage read + the two heal-reconciliation reads — a fixed
    # handful regardless of how many runs are on the page (no per-run query).
    assert len(calls) <= 5
