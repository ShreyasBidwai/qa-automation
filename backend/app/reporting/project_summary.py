"""Per-project summary for the projects-list page (read-time, batched).

Widens the projects list from name/repo/registered to last-run, pass-rate,
open-findings count, and an overall status — computed in a fixed number of grouped
queries regardless of how many projects are on the page (no N+1). It REUSES the
existing definitions: ``pass_rate`` (also used by the runs list) and the inbox's
"currently open" definition (``OpenFindingsReader.open_counts_by_project``), so the
projects-list numbers can never drift from the runs list or the findings inbox.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.lifecycle import STATUS_ERRORED as RUN_STATUS_ERRORED
from app.models.enums import Outcome
from app.models.run import Run
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository

from .open_findings import OpenFindingsReader

# Overall project status (derived, not stored). Deterministic precedence:
# never run > errored last run > open findings need attention > passing.
STATUS_NEVER_RUN = "never_run"
STATUS_ERRORED = "errored"
STATUS_ACTION_NEEDED = "action_needed"
STATUS_PASSING = "passing"


def pass_rate(counts: dict[Outcome, int] | None) -> float | None:
    """passed / total over a run's results, rounded; None when there are no results.

    The single definition of pass-rate, shared by the runs list and the projects
    list (don't re-derive it a second way).
    """
    if not counts:
        return None
    total = sum(counts.values())
    if total == 0:
        return None
    return round(counts.get(Outcome.PASS, 0) / total, 4)


def derive_status(last_run: Run | None, open_findings_count: int) -> str:
    """The overall project status from its latest run + open-findings count.

    Precedence (deterministic): a project that has never run is ``never_run``; a
    latest run that errored (infra/runner failure, not a test outcome) is
    ``errored``; otherwise open findings mean ``action_needed``; else ``passing``.
    """
    if last_run is None:
        return STATUS_NEVER_RUN
    if last_run.status == RUN_STATUS_ERRORED:
        return STATUS_ERRORED
    if open_findings_count > 0:
        return STATUS_ACTION_NEEDED
    return STATUS_PASSING


@dataclass(frozen=True)
class ProjectSummary:
    """The widened, read-time summary for one project (all degrade gracefully)."""

    last_run: Run | None
    pass_rate: float | None
    open_findings_count: int
    status: str


class ProjectSummaryReader:
    """Batched per-project summaries for a page of projects (no N+1)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summaries_for(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, ProjectSummary]:
        """Summaries keyed by project id — a fixed number of grouped queries.

        Three batched reads regardless of page size: latest run per project, outcome
        counts for those runs, and open-findings counts per project. ``project_ids``
        are the caller's already-authorized page, so no extra RBAC is needed here.
        """
        ids = list(project_ids)
        if not ids:
            return {}

        latest = await RunRepository(self._session).latest_run_per_project(ids)
        run_ids = [run.id for run in latest.values()]
        counts_by_run = await ResultRepository(self._session).outcome_counts_by_run(
            ids, run_ids
        )
        open_counts = await OpenFindingsReader(self._session).open_counts_by_project(
            run_ids
        )

        summaries: dict[uuid.UUID, ProjectSummary] = {}
        for project_id in ids:
            run = latest.get(project_id)
            open_count = open_counts.get(project_id, 0)
            summaries[project_id] = ProjectSummary(
                last_run=run,
                pass_rate=pass_rate(counts_by_run.get(run.id)) if run else None,
                open_findings_count=open_count,
                status=derive_status(run, open_count),
            )
        return summaries
