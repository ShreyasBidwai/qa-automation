"""Repository for ``finding_results`` (T7.2) — project-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.finding_result import FindingResult

from .base import ProjectScopedRepository


class FindingResultRepository(ProjectScopedRepository[FindingResult]):
    model = FindingResult

    async def list_for_finding(
        self, project_id: uuid.UUID, finding_id: uuid.UUID
    ) -> list[FindingResult]:
        """The result memberships of one finding, oldest → newest (scoped)."""
        stmt = (
            select(FindingResult)
            .where(
                FindingResult.project_id == project_id,
                FindingResult.finding_id == finding_id,
            )
            .order_by(FindingResult.created_at, FindingResult.id)
        )
        return list((await self.session.scalars(stmt)).all())
