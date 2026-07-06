"""Per-project summary aggregation for the projects list (ADR-0045).

Covers the widened fields from real data, graceful degradation with no runs, that
the open-findings count matches the inbox's definition exactly, the status
derivation, and — the load-bearing property — that the whole page costs a fixed
number of queries regardless of project count (no N+1).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.enums import FindingLayer, OracleSource, Outcome, TriageStatus
from app.models.finding import Finding
from app.models.run import Run
from app.reporting.open_findings import OpenFindingsReader
from app.reporting.project_summary import (
    STATUS_ACTION_NEEDED,
    STATUS_ERRORED,
    STATUS_NEVER_RUN,
    STATUS_PASSING,
    ProjectSummaryReader,
    pass_rate,
)
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def test_pass_rate_excludes_skipped_from_both_sides() -> None:
    # SKIPPED (reachable-but-unverified) is neither pass nor fail — it must not drag a
    # genuinely-passing run's rate down (ADR-0064). 4 pass / (4 pass + 1 fail) = 0.8.
    counts = {Outcome.PASS: 4, Outcome.FAIL: 1, Outcome.SKIPPED: 7}
    assert pass_rate(counts) == 0.8


def test_pass_rate_is_none_when_nothing_was_verified() -> None:
    # A module of only un-verifiable endpoints has NO pass-rate, not a misleading 0%.
    assert pass_rate({Outcome.SKIPPED: 11}) is None
    assert pass_rate({}) is None


async def _project(session: AsyncSession) -> uuid.UUID:
    return (await ProjectRepository(session).add(make_project())).id


async def _run(
    session: AsyncSession, project_id: uuid.UUID, *, day: int, status: str = "passed"
) -> Run:
    return await RunRepository(session).add(
        make_run(project_id, status=status, created_at=_BASE + timedelta(days=day))
    )


async def _results(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    outcomes: Sequence[Outcome],
) -> None:
    case = await TestCaseRepository(session).add(make_test_case(project_id))
    for outcome in outcomes:
        await ResultRepository(session).add(
            make_result(project_id, run_id, case.id, outcome=outcome)
        )


async def _open_finding(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    key: str,
    triage_status: TriageStatus | None = None,
) -> None:
    case = await TestCaseRepository(session).add(make_test_case(project_id))
    result = await ResultRepository(session).add(
        make_result(project_id, run_id, case.id, outcome=Outcome.FAIL)
    )
    await FindingRepository(session).add(
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
    if triage_status is not None:
        await FindingTriageRepository(session).upsert(
            project_id, key, status=triage_status, note=None
        )


# --- the widened fields ------------------------------------------------------


async def test_summary_carries_last_run_pass_rate_open_count_status(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run = await _run(db_session, project_id, day=1, status="failed")
    await _results(db_session, project_id, run.id, [Outcome.PASS, Outcome.PASS])
    # The finding contributes the run's one FAIL result → 2 pass / 3 total.
    await _open_finding(db_session, project_id, run.id, key="BUG#fail")

    summary = (await ProjectSummaryReader(db_session).summaries_for([project_id]))[
        project_id
    ]
    assert summary.last_run is not None and summary.last_run.id == run.id
    assert summary.pass_rate == round(2 / 3, 4)
    assert summary.open_findings_count == 1
    assert summary.status == STATUS_ACTION_NEEDED


async def test_no_runs_degrades_gracefully(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    summary = (await ProjectSummaryReader(db_session).summaries_for([project_id]))[
        project_id
    ]
    assert summary.last_run is None
    assert summary.pass_rate is None
    assert summary.open_findings_count == 0
    assert summary.status == STATUS_NEVER_RUN


async def test_latest_run_wins_and_passing_status(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    await _run(db_session, project_id, day=0, status="failed")  # older
    latest = await _run(db_session, project_id, day=1, status="passed")
    await _results(db_session, project_id, latest.id, [Outcome.PASS, Outcome.PASS])

    summary = (await ProjectSummaryReader(db_session).summaries_for([project_id]))[
        project_id
    ]
    assert summary.last_run is not None and summary.last_run.id == latest.id
    assert summary.pass_rate == 1.0
    assert summary.status == STATUS_PASSING  # no open findings → passing


async def test_errored_status_takes_precedence(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    run = await _run(db_session, project_id, day=1, status="errored")
    await _open_finding(db_session, project_id, run.id, key="X#fail")  # even with one

    summary = (await ProjectSummaryReader(db_session).summaries_for([project_id]))[
        project_id
    ]
    assert summary.status == STATUS_ERRORED


# --- the count matches the inbox exactly -------------------------------------


async def test_open_count_matches_the_inbox_definition(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run = await _run(db_session, project_id, day=1, status="failed")
    await _open_finding(db_session, project_id, run.id, key="OPEN#fail")
    # Muted dispositions are excluded by the inbox — and must be by the count too.
    await _open_finding(
        db_session,
        project_id,
        run.id,
        key="RESOLVED#fail",
        triage_status=TriageStatus.RESOLVED,
    )
    await _open_finding(
        db_session,
        project_id,
        run.id,
        key="WONTFIX#fail",
        triage_status=TriageStatus.WONT_FIX,
    )

    summary = (await ProjectSummaryReader(db_session).summaries_for([project_id]))[
        project_id
    ]
    _, inbox_total = await OpenFindingsReader(db_session).open_findings(
        project_id, limit=100, offset=0
    )
    assert summary.open_findings_count == inbox_total == 1


# --- batched: no N+1 across projects -----------------------------------------


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


async def test_summaries_are_batched_no_n_plus_one(
    counting_session: tuple[AsyncSession, list[int]],
) -> None:
    session, calls = counting_session
    project_ids: list[uuid.UUID] = []
    for i in range(5):
        project_id = await _project(session)
        run = await _run(session, project_id, day=1, status="failed")
        await _results(session, project_id, run.id, [Outcome.PASS, Outcome.FAIL])
        await _open_finding(session, project_id, run.id, key=f"k{i}#fail")
        project_ids.append(project_id)

    calls.clear()
    summaries = await ProjectSummaryReader(session).summaries_for(project_ids)

    assert len(summaries) == 5
    # latest-run-per-project + outcome-counts + (findings + triage + 2 heal reads) —
    # a fixed handful for the whole page, NOT one-per-project (5 projects ⇒ no growth).
    assert len(calls) <= 7
