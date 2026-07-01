"""Repository for ``test_scripts`` (TRD §3)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select

from app.models.test_script import TestScript

from .base import ProjectScopedRepository


class TestScriptRepository(ProjectScopedRepository[TestScript]):
    model = TestScript

    async def latest_by_case(
        self, project_id: uuid.UUID, case_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, TestScript]:
        """The latest script per case, keyed by ``test_case_id`` — batched (no N+1).

        The viewer shows one runnable script per case; ordering by created_at and
        letting the last write win yields the most recent generation for each.
        """
        ids = set(case_ids)
        if not ids:
            return {}
        stmt = (
            select(TestScript)
            .where(
                TestScript.project_id == project_id,
                TestScript.test_case_id.in_(ids),
            )
            .order_by(TestScript.created_at)
        )
        by_case: dict[uuid.UUID, TestScript] = {}
        for script in (await self.session.scalars(stmt)).all():
            by_case[script.test_case_id] = script  # last (newest) wins
        return by_case

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
