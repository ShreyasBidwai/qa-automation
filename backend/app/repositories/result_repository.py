"""Repository for ``results`` (TRD §3)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select

from app.models.enums import Outcome
from app.models.result import Result

from .base import ProjectScopedRepository


class ResultRepository(ProjectScopedRepository[Result]):
    model = Result

    async def list_for_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[Result]:
        stmt = (
            select(Result)
            .where(Result.project_id == project_id, Result.run_id == run_id)
            .order_by(Result.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_many(
        self, project_id: uuid.UUID, result_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, Result]:
        """Fetch many results by id in one query, keyed by id (scoped, no N+1)."""
        ids = set(result_ids)
        if not ids:
            return {}
        stmt = select(Result).where(Result.project_id == project_id, Result.id.in_(ids))
        return {r.id: r for r in (await self.session.scalars(stmt)).all()}

    async def passing_case_ids_in_runs(
        self, project_id: uuid.UUID, run_ids: Sequence[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Test cases that PASSED in any of ``run_ids`` (project-scoped, one query).

        The "previously passing" gate for self-healing (B8): only a test that was
        green before is a candidate to heal when it newly fails. Empty if no runs.
        """
        if not run_ids:
            return set()
        stmt = select(Result.test_case_id).where(
            Result.project_id == project_id,
            Result.run_id.in_(run_ids),
            Result.outcome == Outcome.PASS,
        )
        return set((await self.session.scalars(stmt)).all())

    async def outcome_counts_for_runs(
        self, project_id: uuid.UUID, run_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, dict[Outcome, int]]:
        """Outcome counts grouped by run, for a set of runs (one query, scoped).

        The backing aggregate for per-run pass rates in the runs list.
        """
        if not run_ids:
            return {}
        stmt = (
            select(Result.run_id, Result.outcome, func.count())
            .where(Result.project_id == project_id, Result.run_id.in_(run_ids))
            .group_by(Result.run_id, Result.outcome)
        )
        counts: dict[uuid.UUID, dict[Outcome, int]] = {}
        for run_id, outcome, count in (await self.session.execute(stmt)).all():
            counts.setdefault(run_id, {})[outcome] = int(count)
        return counts

    async def outcome_counts_by_run(
        self,
        project_ids: Sequence[uuid.UUID],
        run_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, dict[Outcome, int]]:
        """Outcome counts grouped by run across MANY projects — one grouped query.

        The cross-project sibling of :meth:`outcome_counts_for_runs` (which is scoped
        to a single project): backs per-run pass rates for the projects-list page in
        one statement, no N+1. Scoped to the page's already-authorized ``project_ids``.
        """
        if not run_ids:
            return {}
        stmt = (
            select(Result.run_id, Result.outcome, func.count())
            .where(
                Result.project_id.in_(list(project_ids)),
                Result.run_id.in_(list(run_ids)),
            )
            .group_by(Result.run_id, Result.outcome)
        )
        counts: dict[uuid.UUID, dict[Outcome, int]] = {}
        for run_id, outcome, count in (await self.session.execute(stmt)).all():
            counts.setdefault(run_id, {})[outcome] = int(count)
        return counts
