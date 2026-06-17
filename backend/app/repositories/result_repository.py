"""Repository for ``results`` (TRD §3)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

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
