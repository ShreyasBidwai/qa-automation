"""Repository for ``finding_results`` (T7.2) — project-scoped."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

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

    async def list_for_findings(
        self, project_id: uuid.UUID, finding_ids: Sequence[uuid.UUID]
    ) -> list[FindingResult]:
        """Result memberships for many findings in one query (scoped, no N+1).

        The batched form of :meth:`list_for_finding` — the backing read for
        assembling evidence across a whole run's findings. Ordered
        deterministically so each finding's members keep a stable order.
        """
        if not finding_ids:
            return []
        stmt = (
            select(FindingResult)
            .where(
                FindingResult.project_id == project_id,
                FindingResult.finding_id.in_(finding_ids),
            )
            .order_by(FindingResult.created_at, FindingResult.id)
        )
        return list((await self.session.scalars(stmt)).all())
