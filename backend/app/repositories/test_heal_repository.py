"""Repository for ``test_heals`` (B8) — project-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.test_heal import STATUS_PROPOSED, TestHeal

from .base import ProjectScopedRepository


class TestHealRepository(ProjectScopedRepository[TestHeal]):
    model = TestHeal

    async def find_dedup(
        self,
        project_id: uuid.UUID,
        test_case_id: uuid.UUID,
        before_addr: str,
        after_addr: str,
    ) -> TestHeal | None:
        """The existing heal for this exact re-addressing, if any (idempotency).

        Backs get-or-create so re-scanning a run never duplicates a heal — the same
        ``(test_case, before, after)`` is one row, matching the unique constraint.
        """
        stmt = select(TestHeal).where(
            TestHeal.project_id == project_id,
            TestHeal.test_case_id == test_case_id,
            TestHeal.before_addr == before_addr,
            TestHeal.after_addr == after_addr,
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def list_for_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[TestHeal]:
        stmt = (
            select(TestHeal)
            .where(TestHeal.project_id == project_id, TestHeal.run_id == run_id)
            .order_by(TestHeal.created_at, TestHeal.id)
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_proposed(self, project_id: uuid.UUID) -> list[TestHeal]:
        """The review queue: heals awaiting a human decision (project-scoped)."""
        stmt = (
            select(TestHeal)
            .where(
                TestHeal.project_id == project_id,
                TestHeal.status == STATUS_PROPOSED,
            )
            .order_by(TestHeal.created_at, TestHeal.id)
        )
        return list((await self.session.scalars(stmt)).all())
