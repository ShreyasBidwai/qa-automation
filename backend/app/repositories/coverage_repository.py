"""Repository for ``coverage`` (TRD §3)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.coverage import Coverage

from .base import ProjectScopedRepository


class CoverageRepository(ProjectScopedRepository[Coverage]):
    model = Coverage

    async def list_for_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[Coverage]:
        stmt = (
            select(Coverage)
            .where(Coverage.project_id == project_id, Coverage.run_id == run_id)
            .order_by(Coverage.created_at)
        )
        return list((await self.session.scalars(stmt)).all())
