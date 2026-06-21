"""Open-findings aggregation (ADR-0028) — the Findings inbox.

"Currently open" = each project's LATEST run, joined to triage, excluding
resolved / wont_fix / false_positive, deduped by root_cause_key, ranked by
severity. These are the gated semantics — tested hard at the reader level with
full control over runs/triage; the API wiring is covered in test_api.py.
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


async def _run(session: AsyncSession, project_id: uuid.UUID, day: int) -> uuid.UUID:
    run = await RunRepository(session).add(
        make_run(project_id, created_at=_BASE + timedelta(days=day))
    )
    return run.id


async def _seed_finding(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    key: str,
    severity: str = "major",
    oracle: OracleSource = OracleSource.RULE_DERIVED,
) -> Finding:
    case = await TestCaseRepository(session).add(
        make_test_case(project_id, oracle_source=oracle)
    )
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
            oracle_source=oracle,
            confidence_mixed=False,
            expected={},
            location={},
            severity=severity,
            status="new",
        )
    )


async def _keys(reader: OpenFindingsReader, project_id: uuid.UUID | None) -> list[str]:
    page, _ = await reader.open_findings(project_id, limit=100, offset=0)
    return [item.finding.root_cause_key for item in page]


async def test_only_latest_run_findings_are_open(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    old = await _run(db_session, project_id, 0)
    latest = await _run(db_session, project_id, 1)
    await _seed_finding(db_session, project_id, old, key="OLD#fail")
    await _seed_finding(db_session, project_id, latest, key="NEW#fail")

    keys = await _keys(OpenFindingsReader(db_session), project_id)
    assert keys == ["NEW#fail"]  # the older run's finding is not "currently open"


async def test_finding_absent_from_latest_run_does_not_appear(
    db_session: AsyncSession,
) -> None:
    """A key open in an older run but NOT reproduced by the latest run is gone."""
    project_id = await _project(db_session)
    old = await _run(db_session, project_id, 0)
    latest = await _run(db_session, project_id, 1)
    await _seed_finding(db_session, project_id, old, key="GONE#fail")
    await _seed_finding(db_session, project_id, latest, key="STILL#fail")

    assert await _keys(OpenFindingsReader(db_session), project_id) == ["STILL#fail"]


async def test_muted_and_resolved_are_excluded(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    latest = await _run(db_session, project_id, 0)
    for key in ("OPEN#f", "ACK#f", "RESOLVED#f", "WONTFIX#f", "FALSEPOS#f"):
        await _seed_finding(db_session, project_id, latest, key=key)
    triage = FindingTriageRepository(db_session)
    for key, status in [
        ("ACK#f", TriageStatus.ACKNOWLEDGED),
        ("RESOLVED#f", TriageStatus.RESOLVED),
        ("WONTFIX#f", TriageStatus.WONT_FIX),
        ("FALSEPOS#f", TriageStatus.FALSE_POSITIVE),
    ]:
        await triage.upsert(project_id, key, status=status, note=None)

    # open + acknowledged remain; resolved / wont_fix / false_positive are excluded.
    assert set(await _keys(OpenFindingsReader(db_session), project_id)) == {
        "OPEN#f",
        "ACK#f",
    }


async def test_wont_fix_root_cause_does_not_appear(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    latest = await _run(db_session, project_id, 0)
    await _seed_finding(db_session, project_id, latest, key="MUTED#fail")
    await FindingTriageRepository(db_session).upsert(
        project_id, "MUTED#fail", status=TriageStatus.WONT_FIX, note="known"
    )
    assert await _keys(OpenFindingsReader(db_session), project_id) == []


async def test_ranked_by_severity(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    latest = await _run(db_session, project_id, 0)
    await _seed_finding(db_session, project_id, latest, key="minor#f", severity="minor")
    await _seed_finding(
        db_session, project_id, latest, key="crit#f", severity="critical"
    )
    await _seed_finding(db_session, project_id, latest, key="major#f", severity="major")

    assert await _keys(OpenFindingsReader(db_session), project_id) == [
        "crit#f",
        "major#f",
        "minor#f",
    ]


async def test_global_spans_projects_and_dedupes_per_project(
    db_session: AsyncSession,
) -> None:
    p1 = await _project(db_session)
    p2 = await _project(db_session)
    r1 = await _run(db_session, p1, 0)
    r2 = await _run(db_session, p2, 0)
    # Same root_cause_key in two projects = two distinct issues (kept separate).
    await _seed_finding(db_session, p1, r1, key="shared#fail", severity="critical")
    await _seed_finding(db_session, p2, r2, key="shared#fail", severity="minor")
    # Mute it in p1 only — p2's must still show.
    await FindingTriageRepository(db_session).upsert(
        p1, "shared#fail", status=TriageStatus.RESOLVED, note=None
    )

    page, total = await OpenFindingsReader(db_session).open_findings(
        None, limit=100, offset=0
    )
    assert total == 1
    pairs = [(item.finding.project_id, item.finding.root_cause_key) for item in page]
    assert pairs == [(p2, "shared#fail")]


async def test_project_with_no_runs_has_no_open_findings(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    page, total = await OpenFindingsReader(db_session).open_findings(
        project_id, limit=10, offset=0
    )
    assert (page, total) == ([], 0)


async def test_latest_run_with_no_findings_is_empty(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    await _run(db_session, project_id, 0)  # an all-pass run produces no findings
    page, total = await OpenFindingsReader(db_session).open_findings(
        project_id, limit=10, offset=0
    )
    assert (page, total) == ([], 0)


async def test_soft_deleted_project_is_excluded(db_session: AsyncSession) -> None:
    keep = await _project(db_session)
    drop = await _project(db_session)
    await _seed_finding(db_session, keep, await _run(db_session, keep, 0), key="KEEP#f")
    await _seed_finding(db_session, drop, await _run(db_session, drop, 0), key="DROP#f")
    await ProjectRepository(db_session).soft_delete(drop)

    assert await _keys(OpenFindingsReader(db_session), None) == ["KEEP#f"]


async def test_pagination(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    latest = await _run(db_session, project_id, 0)
    for i in range(5):
        await _seed_finding(
            db_session, project_id, latest, key=f"k{i}#f", severity="major"
        )
    reader = OpenFindingsReader(db_session)
    page, total = await reader.open_findings(project_id, limit=2, offset=2)
    assert total == 5
    assert len(page) == 2


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


async def test_open_findings_selection_is_batched_no_n_plus_one(
    counting_session: tuple[AsyncSession, list[int]],
) -> None:
    session, calls = counting_session
    project_id = await _project(session)
    latest = await _run(session, project_id, 0)
    for i in range(6):
        await _seed_finding(session, project_id, latest, key=f"n{i}#f")

    reader = OpenFindingsReader(session)
    calls.clear()
    page, total = await reader.open_findings(project_id, limit=100, offset=0)

    assert total == 6
    # Latest-run DISTINCT-ON + findings read + triage read — a fixed handful of
    # statements regardless of finding count (no per-finding query).
    assert len(calls) <= 4
