"""AccountDashboardReader — account-wide aggregation (ADR-0065).

Covers: cross-project outcome totals + a skip-aware pass-rate, the day-bucketed trend,
open-findings severity totals, project-health ordering + status, recent activity, and
the empty account — all from the shared batched readers.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FindingLayer, OracleSource, Outcome
from app.models.finding import Finding
from app.models.run import Run
from app.reporting.account_dashboard import AccountDashboardReader
from app.repositories.finding_repository import FindingRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case

_NOW = datetime(2026, 2, 1, tzinfo=UTC)


async def _project(session: AsyncSession, name: str) -> uuid.UUID:
    return (await ProjectRepository(session).add(make_project(name=name))).id


async def _run(
    session: AsyncSession, project_id: uuid.UUID, *, day: int, status: str = "passed"
) -> Run:
    return await RunRepository(session).add(
        make_run(project_id, status=status, created_at=_NOW - timedelta(days=day))
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
    session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID, *, severity: str
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
            root_cause_key=f"{project_id}-{severity}",
            explains_count=1,
            title="f",
            layer=FindingLayer.API,
            oracle_source=OracleSource.RULE_DERIVED,
            confidence_mixed=False,
            expected={},
            location={},
            severity=severity,
            status="new",
        )
    )


async def test_dashboard_aggregates_outcomes_findings_health_and_trend(
    db_session: AsyncSession,
) -> None:
    alpha = await _project(db_session, "Alpha")
    beta = await _project(db_session, "Beta")
    # Alpha: latest run mixes pass/fail/skip and has an open critical finding.
    a_run = await _run(db_session, alpha, day=1, status="failed")
    await _results(
        db_session, alpha, a_run.id, [Outcome.PASS, Outcome.PASS, Outcome.SKIPPED]
    )
    await _open_finding(db_session, alpha, a_run.id, severity="critical")
    # Beta: latest run is all reachable-but-unverified (skips) — a clean, 0-verified run.
    b_run = await _run(db_session, beta, day=2, status="passed")
    await _results(db_session, beta, b_run.id, [Outcome.SKIPPED, Outcome.SKIPPED])

    dash = await AccountDashboardReader(db_session).build(
        {alpha: "Alpha", beta: "Beta"}, range_days=30, now=_NOW
    )

    assert dash.projects_total == 2
    # Outcomes summed across both runs; SKIPPED excluded from the rate: 2 / (2+1) = 0.67.
    assert dash.outcomes["pass"] == 2
    assert dash.outcomes["fail"] == 1  # the finding's failing result
    assert dash.outcomes["skipped"] == 3
    assert dash.tests_total == 6
    assert dash.pass_rate == round(2 / 3, 4)
    # Open findings severity totals.
    assert dash.open_findings["critical"] == 1
    assert dash.open_findings["total"] == 1
    # Statuses: Alpha has an open finding → action_needed; Beta clean → passing.
    assert dash.projects_by_status["action_needed"] == 1
    assert dash.projects_by_status["passing"] == 1
    # Health table: the project needing attention (Alpha) leads.
    assert [row.name for row in dash.project_health] == ["Alpha", "Beta"]
    assert dash.project_health[0].open_findings == 1
    # Trend: two days (day-1 Alpha, day-2 Beta), oldest → newest.
    assert [p.date for p in dash.trend] == [
        (_NOW - timedelta(days=2)).date().isoformat(),
        (_NOW - timedelta(days=1)).date().isoformat(),
    ]
    assert dash.runs_total == 2
    assert len(dash.recent_runs) == 2


async def test_range_excludes_runs_older_than_the_window(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session, "Alpha")
    recent = await _run(db_session, project, day=3)
    await _results(db_session, project, recent.id, [Outcome.PASS])
    old = await _run(db_session, project, day=90)  # outside a 30-day window
    await _results(db_session, project, old.id, [Outcome.FAIL, Outcome.FAIL])

    dash = await AccountDashboardReader(db_session).build(
        {project: "Alpha"}, range_days=30, now=_NOW
    )

    # Only the in-range run counts toward the range-scoped totals/trend.
    assert dash.runs_total == 1
    assert dash.outcomes["fail"] == 0
    assert dash.pass_rate == 1.0
    assert len(dash.trend) == 1


async def test_empty_account_degrades_gracefully(db_session: AsyncSession) -> None:
    dash = await AccountDashboardReader(db_session).build({}, range_days=30, now=_NOW)
    assert dash.projects_total == 0
    assert dash.pass_rate is None
    assert dash.open_findings["total"] == 0
    assert dash.trend == []
    assert dash.recent_runs == []
