"""Repository for ``runs`` (TRD §3)."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select

from app.models.run import Run

from .base import ProjectScopedRepository


class RunRepository(ProjectScopedRepository[Run]):
    model = Run

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
