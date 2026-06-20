"""Triage disposition keyed by the logical issue (ADR-0027).

Covers the upsert (idempotent, keyed by ``(project_id, root_cause_key)``), the
batched read, and the model's whole point: a disposition follows the issue across
runs, not the per-run finding row. The end-to-end across-runs proof through the
API lives in test_api.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.enums import FindingLayer, OracleSource, Outcome, TriageStatus
from app.models.finding import Finding
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case

_DAY = datetime(2026, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def project_id(db_session: AsyncSession) -> uuid.UUID:
    project = await ProjectRepository(db_session).add(make_project())
    return project.id


async def _seed_finding(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    key: str,
) -> Finding:
    case = await TestCaseRepository(session).add(make_test_case(project_id))
    result = await ResultRepository(session).add(
        make_result(project_id, run_id, case.id, outcome=Outcome.FAIL)
    )
    return await FindingRepository(session).add(
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
            severity="major",
            status="new",
        )
    )


async def test_upsert_inserts_then_updates_in_place(
    db_session: AsyncSession, project_id: uuid.UUID
) -> None:
    repo = FindingTriageRepository(db_session)
    key = "endpoint=POST api/orders#fail|status=500"

    first = await repo.upsert(
        project_id, key, status=TriageStatus.ACKNOWLEDGED, note="looking"
    )
    assert first.status is TriageStatus.ACKNOWLEDGED
    assert first.note == "looking"
    assert first.triaged_at is not None

    # Same issue key → updates the same row, no duplicate (idempotent upsert).
    second = await repo.upsert(project_id, key, status=TriageStatus.WONT_FIX, note=None)
    assert second.id == first.id
    assert second.status is TriageStatus.WONT_FIX
    assert second.note is None

    records = await repo.get_for_keys(project_id, [key])
    assert len(records) == 1
    assert records[key].status is TriageStatus.WONT_FIX


async def test_get_for_keys_is_keyed_and_handles_absent(
    db_session: AsyncSession, project_id: uuid.UUID
) -> None:
    repo = FindingTriageRepository(db_session)
    await repo.upsert(project_id, "key-a", status=TriageStatus.RESOLVED, note=None)

    records = await repo.get_for_keys(project_id, ["key-a", "key-missing"])
    assert set(records) == {"key-a"}  # absent key simply not present
    assert records["key-a"].status is TriageStatus.RESOLVED
    assert await repo.get_for_keys(project_id, []) == {}


async def test_triage_follows_the_issue_across_runs(
    db_session: AsyncSession, project_id: uuid.UUID
) -> None:
    """The model's core property: triage is attached to the root_cause_key, so a
    later run producing the same key inherits the disposition."""
    runs = RunRepository(db_session)
    r1 = await runs.add(make_run(project_id, created_at=_DAY))
    r2 = await runs.add(make_run(project_id, created_at=_DAY + timedelta(days=1)))
    key = "endpoint=POST api/orders#fail|status=500"
    f1 = await _seed_finding(db_session, project_id, r1.id, key)
    f2 = await _seed_finding(db_session, project_id, r2.id, key)
    assert f1.id != f2.id  # genuinely different per-run rows…

    # Triage the issue while looking at run 1's finding.
    await FindingTriageRepository(db_session).upsert(
        project_id, f1.root_cause_key, status=TriageStatus.WONT_FIX, note=None
    )

    # …run 2's finding (same key) carries the disposition.
    records = await FindingTriageRepository(db_session).get_for_keys(
        project_id, [f2.root_cause_key]
    )
    assert records[f2.root_cause_key].status is TriageStatus.WONT_FIX


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


async def test_get_for_keys_reads_many_in_one_query(
    counting_session: tuple[AsyncSession, list[int]],
) -> None:
    session, calls = counting_session
    project = await ProjectRepository(session).add(make_project())
    repo = FindingTriageRepository(session)
    keys = [f"endpoint=POST api/r{i}#fail" for i in range(5)]
    for key in keys:
        await repo.upsert(project.id, key, status=TriageStatus.RESOLVED, note=None)

    calls.clear()
    records = await repo.get_for_keys(project.id, keys)

    assert len(records) == 5
    assert len(calls) == 1  # one batched SELECT for all keys — no N+1
