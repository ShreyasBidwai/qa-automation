"""Account-wide dashboard aggregation — the post-login landing insight (ADR-0065).

One read that answers "how is my whole account doing?" across every project the user's
orgs own: headline health, open-findings severity, a pass-rate/outcome TREND over a
time window, per-project health rows, and recent activity. Composed entirely from the
existing batched readers (``ProjectSummaryReader``, ``OpenFindingsReader``,
``ResultRepository``) so it inherits their "currently open" / pass-rate definitions and
their no-N+1 discipline — a fixed number of grouped queries regardless of account size.

Two scopes, deliberately: CURRENT state (projects, statuses, open findings, per-project
health) reflects each project's latest run; the RANGE-scoped parts (runs, outcomes,
pass-rate, trend, recent activity) honour the ``range_days`` filter. Pure aggregation,
read-only, org-scoped by the caller.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Outcome
from app.models.run import Run
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository

from .open_findings import OpenFindingsReader
from .project_summary import ProjectSummary, ProjectSummaryReader, pass_rate

# Bounds so a pathological account can't produce an unbounded read. The trend caps the
# runs it buckets; recent activity is a short feed. Projects are already page-bounded.
_MAX_TREND_RUNS = 5000
_RECENT_RUNS = 8
_MAX_PROJECTS = 500
_COUNTED_SEVERITIES = ("critical", "major", "minor")


@dataclass(frozen=True)
class ProjectHealthRow:
    project_id: uuid.UUID
    name: str
    status: str
    pass_rate: float | None
    open_findings: int
    last_run_at: datetime | None


@dataclass(frozen=True)
class TrendPoint:
    """One day's outcome roll-up (buckets by run ``created_at``)."""

    date: str  # YYYY-MM-DD (UTC)
    runs: int
    passed: int
    failed: int
    errored: int
    skipped: int
    pass_rate: float | None  # verified: passed / (passed + failed + errored)


@dataclass(frozen=True)
class RecentRunRow:
    run_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    mode: str
    status: str
    pass_rate: float | None
    created_at: datetime


@dataclass(frozen=True)
class AccountDashboard:
    range_days: int
    # CURRENT state (latest run per project).
    projects_total: int
    projects_by_status: dict[str, int]
    open_findings: dict[str, int]  # critical / major / minor / total
    project_health: list[ProjectHealthRow]
    # RANGE-scoped (honours range_days).
    runs_total: int
    tests_total: int
    outcomes: dict[str, int]  # pass / fail / error / skipped
    pass_rate: float | None
    trend: list[TrendPoint]
    recent_runs: list[RecentRunRow] = field(default_factory=list)


def _day(moment: datetime) -> str:
    return moment.astimezone(UTC).date().isoformat()


class AccountDashboardReader:
    """Builds :class:`AccountDashboard` for a set of org-scoped project ids."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(
        self,
        project_ids_and_names: dict[uuid.UUID, str],
        *,
        range_days: int,
        now: datetime | None = None,
    ) -> AccountDashboard:
        """Aggregate the dashboard. ``project_ids_and_names`` is the caller's already-
        authorized (org-scoped) project id → name map; ``range_days`` bounds the trend
        and range cards. ``now`` is injectable for deterministic tests."""
        now = now or datetime.now(UTC)
        since = now - timedelta(days=range_days)
        ids = list(project_ids_and_names)[:_MAX_PROJECTS]

        summaries = await ProjectSummaryReader(self._session).summaries_for(ids)
        health, by_status = self._project_health(project_ids_and_names, summaries)
        open_findings = await self._open_severity(summaries)

        runs = await RunRepository(self._session).list_for_projects(
            ids, since=since, limit=_MAX_TREND_RUNS
        )
        counts_by_run = await ResultRepository(self._session).outcome_counts_by_run(
            ids, [run.id for run in runs]
        )
        outcomes = self._sum_outcomes(runs, counts_by_run)
        trend = self._trend(runs, counts_by_run)
        recent = self._recent(runs, counts_by_run, project_ids_and_names)

        return AccountDashboard(
            range_days=range_days,
            projects_total=len(ids),
            projects_by_status=by_status,
            open_findings=open_findings,
            project_health=health,
            runs_total=len(runs),
            tests_total=sum(outcomes.values()),
            outcomes=outcomes,
            # pass_rate() already excludes SKIPPED from both sides (ADR-0064).
            pass_rate=pass_rate({Outcome(k): v for k, v in outcomes.items()}),
            trend=trend,
            recent_runs=recent,
        )

    # --- current state -------------------------------------------------------

    def _project_health(
        self,
        names: dict[uuid.UUID, str],
        summaries: dict[uuid.UUID, ProjectSummary],
    ) -> tuple[list[ProjectHealthRow], dict[str, int]]:
        rows: list[ProjectHealthRow] = []
        by_status: dict[str, int] = defaultdict(int)
        for project_id, name in names.items():
            summary = summaries.get(project_id)
            status = summary.status if summary else "never_run"
            by_status[status] += 1
            rows.append(
                ProjectHealthRow(
                    project_id=project_id,
                    name=name,
                    status=status,
                    pass_rate=summary.pass_rate if summary else None,
                    open_findings=summary.open_findings_count if summary else 0,
                    last_run_at=(
                        summary.last_run.created_at
                        if summary and summary.last_run
                        else None
                    ),
                )
            )
        # Most-open-findings first, then worst pass-rate — the projects needing
        # attention lead the table; a name tiebreak keeps the order deterministic.
        rows.sort(
            key=lambda r: (
                -r.open_findings,
                r.pass_rate if r.pass_rate is not None else 2,
                r.name,
            )
        )
        return rows, dict(by_status)

    async def _open_severity(
        self, summaries: dict[uuid.UUID, ProjectSummary]
    ) -> dict[str, int]:
        latest_run_ids = [
            s.last_run.id for s in summaries.values() if s.last_run is not None
        ]
        per_run = await OpenFindingsReader(self._session).severity_counts_by_run(
            latest_run_ids
        )
        totals = {severity: 0 for severity in _COUNTED_SEVERITIES}
        for buckets in per_run.values():
            for severity in _COUNTED_SEVERITIES:
                totals[severity] += buckets.get(severity, 0)
        totals["total"] = sum(totals[severity] for severity in _COUNTED_SEVERITIES)
        return totals

    # --- range-scoped --------------------------------------------------------

    @staticmethod
    def _sum_outcomes(
        runs: list[Run],
        counts_by_run: dict[uuid.UUID, dict[Outcome, int]],
    ) -> dict[str, int]:
        totals = {outcome.value: 0 for outcome in Outcome}
        for run in runs:
            for outcome, n in counts_by_run.get(run.id, {}).items():
                totals[outcome.value] += n
        return totals

    def _trend(
        self,
        runs: list[Run],
        counts_by_run: dict[uuid.UUID, dict[Outcome, int]],
    ) -> list[TrendPoint]:
        buckets: dict[str, dict[Outcome, int]] = defaultdict(lambda: defaultdict(int))
        run_counts: dict[str, int] = defaultdict(int)
        for run in runs:
            day = _day(run.created_at)
            run_counts[day] += 1
            for outcome, n in counts_by_run.get(run.id, {}).items():
                buckets[day][outcome] += n
        points: list[TrendPoint] = []
        for day in sorted(buckets):  # oldest → newest for a left-to-right chart
            b = buckets[day]
            points.append(
                TrendPoint(
                    date=day,
                    runs=run_counts[day],
                    passed=b.get(Outcome.PASS, 0),
                    failed=b.get(Outcome.FAIL, 0),
                    errored=b.get(Outcome.ERROR, 0),
                    skipped=b.get(Outcome.SKIPPED, 0),
                    pass_rate=pass_rate(dict(b)),
                )
            )
        return points

    def _recent(
        self,
        runs: list[Run],
        counts_by_run: dict[uuid.UUID, dict[Outcome, int]],
        names: dict[uuid.UUID, str],
    ) -> list[RecentRunRow]:
        # ``runs`` is already newest-first (RunRepository), so the head is the feed.
        return [
            RecentRunRow(
                run_id=run.id,
                project_id=run.project_id,
                project_name=names.get(run.project_id, "—"),
                mode=run.mode.value,
                status=run.status,
                pass_rate=pass_rate(counts_by_run.get(run.id)),
                created_at=run.created_at,
            )
            for run in runs[:_RECENT_RUNS]
        ]
