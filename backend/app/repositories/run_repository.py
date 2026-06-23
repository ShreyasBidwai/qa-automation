"""Repository for ``runs`` (TRD §3)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, func, or_, select

from app.models.run import Run

from .base import ProjectScopedRepository


class RunRepository(ProjectScopedRepository[Run]):
    model = Run

    async def latest_run_per_project(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Run]:
        """The most-recent run per project, batched — ONE ``DISTINCT ON`` query.

        Same latest-run ordering as the open-findings reader (``created_at`` desc,
        ``id`` desc as the deterministic tiebreaker). Keyed by ``project_id``;
        projects with no runs are simply absent. Scoped to the passed ``project_ids``
        (the caller's already-authorized page) — no N+1 across projects.
        """
        ids = list(project_ids)
        if not ids:
            return {}
        stmt = (
            select(Run)
            .where(Run.project_id.in_(ids))
            .order_by(Run.project_id, Run.created_at.desc(), Run.id.desc())
            .distinct(Run.project_id)
        )
        return {run.project_id: run for run in (await self.session.scalars(stmt)).all()}

    async def list_for_project(
        self, project_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Run]:
        """A bounded page of a project's runs, newest first (deterministic)."""
        stmt = (
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Run).where(Run.project_id == project_id)
        return int(await self.session.scalar(stmt) or 0)

    async def prior_run_ids(
        self, project_id: uuid.UUID, run_id: uuid.UUID, *, limit: int
    ) -> list[uuid.UUID]:
        """The ``limit`` runs immediately before ``run_id``, oldest → newest.

        Ordered by ``(created_at, id)`` (deterministic); the bounded history window
        for cross-run classification (ADR-0023). Empty if the run is unknown or is
        the project's first.
        """
        current = await self.get(project_id, run_id)
        if current is None:
            return []
        before = or_(
            Run.created_at < current.created_at,
            and_(Run.created_at == current.created_at, Run.id < current.id),
        )
        stmt = (
            select(Run.id)
            .where(Run.project_id == project_id, before)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit)
        )
        recent_first = list((await self.session.scalars(stmt)).all())
        return list(reversed(recent_first))  # oldest → newest
