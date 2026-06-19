"""Repository for ``findings`` (T7.1) — project-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.finding import Finding

from .base import ProjectScopedRepository


class FindingRepository(ProjectScopedRepository[Finding]):
    model = Finding

    async def list_for_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[Finding]:
        """All findings for a run in deterministic order (project-scoped).

        Ordered by ``root_cause_key`` — a stable, content-derived key (ADR-0021),
        so the same run always lists its findings the same way (created_at/id are
        not deterministic across re-assembly).
        """
        stmt = (
            select(Finding)
            .where(Finding.project_id == project_id, Finding.run_id == run_id)
            .order_by(Finding.root_cause_key)
        )
        return list((await self.session.scalars(stmt)).all())
