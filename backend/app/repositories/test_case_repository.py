"""Repository for ``test_cases``, including the version-fork helper (TRD §3)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.models.enums import TestType
from app.models.test_case import TestCase

from .base import ProjectScopedRepository


class TestCaseRepository(ProjectScopedRepository[TestCase]):
    model = TestCase

    async def list_by_type(
        self, project_id: uuid.UUID, type_: TestType
    ) -> list[TestCase]:
        stmt = (
            select(TestCase)
            .where(TestCase.project_id == project_id, TestCase.type == type_)
            .order_by(TestCase.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def new_version(self, prior: TestCase, **overrides: Any) -> TestCase:
        """Fork ``prior`` into a new row: version + 1, parent_version_id = prior.id.

        The prior row is left untouched — the mechanical basis for the
        never-clobber rule (TRD §3 versioning). Callers (services) decide *when*
        to fork and supply field changes via ``overrides`` (e.g.
        ``edited_by_human=True``). No policy lives here.
        """
        data: dict[str, Any] = {
            "project_id": prior.project_id,
            "type": prior.type,
            "layer": prior.layer,
            "target_node": prior.target_node,
            "preconditions": prior.preconditions,
            "steps": prior.steps,
            "expected": prior.expected,
            "oracle_source": prior.oracle_source,
            "authored_by": prior.authored_by,
            "edited_by_human": prior.edited_by_human,
            "requirement_link": prior.requirement_link,
            "status": prior.status,
            "version": prior.version + 1,
            "parent_version_id": prior.id,
        }
        data.update(overrides)
        new_case = TestCase(**data)
        self.session.add(new_case)
        await self.session.flush()
        return new_case
