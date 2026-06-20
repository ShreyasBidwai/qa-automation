"""Repository for ``results`` (TRD §3)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

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
