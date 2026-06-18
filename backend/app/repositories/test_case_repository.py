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
        never-clobber rule (TRD §3 versioning). The new row stays in the same
        lineage (``lineage_id`` carried forward). It is created NON-current by
        default so this helper can never create a second current row for the
        lineage (the partial unique index would reject it); the caller owns the
        one-current handoff — retire the old current, then promote the fork via
        ``is_current=True``. Callers (services) decide *when* to fork and supply
        field changes via ``overrides``. No policy lives here.
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
            "lineage_id": prior.lineage_id,
            "origin": prior.origin,
            "edited_by": prior.edited_by,
            "is_current": False,
        }
        data.update(overrides)
        new_case = TestCase(**data)
        self.session.add(new_case)
        await self.session.flush()
        return new_case

    async def get_current(
        self, project_id: uuid.UUID, lineage_id: uuid.UUID
    ) -> TestCase | None:
        """The single current version of a lineage, or None (project-scoped)."""
        stmt = select(TestCase).where(
            TestCase.project_id == project_id,
            TestCase.lineage_id == lineage_id,
            TestCase.is_current.is_(True),
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def get_history(
        self, project_id: uuid.UUID, lineage_id: uuid.UUID
    ) -> list[TestCase]:
        """All versions of a lineage, oldest → newest (project-scoped)."""
        stmt = (
            select(TestCase)
            .where(
                TestCase.project_id == project_id,
                TestCase.lineage_id == lineage_id,
            )
            .order_by(TestCase.version)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_version(
        self, project_id: uuid.UUID, lineage_id: uuid.UUID, version: int
    ) -> TestCase | None:
        """One specific version of a lineage, or None (project-scoped)."""
        stmt = select(TestCase).where(
            TestCase.project_id == project_id,
            TestCase.lineage_id == lineage_id,
            TestCase.version == version,
        )
        return (await self.session.scalars(stmt)).one_or_none()
