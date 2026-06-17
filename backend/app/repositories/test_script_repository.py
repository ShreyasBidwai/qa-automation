"""Repository for ``test_scripts`` (TRD §3)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.test_script import TestScript

from .base import ProjectScopedRepository


class TestScriptRepository(ProjectScopedRepository[TestScript]):
    model = TestScript

    async def list_for_test_case(
        self, project_id: uuid.UUID, test_case_id: uuid.UUID
    ) -> list[TestScript]:
        stmt = (
            select(TestScript)
            .where(
                TestScript.project_id == project_id,
                TestScript.test_case_id == test_case_id,
            )
            .order_by(TestScript.created_at)
        )
        return list((await self.session.scalars(stmt)).all())
