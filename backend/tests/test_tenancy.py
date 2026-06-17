"""Tenancy isolation — a query scoped to project A never returns B's rows."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TestType
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_test_case


async def test_queries_are_project_scoped(db_session: AsyncSession) -> None:
    project_a = make_project(slug=f"a-{uuid.uuid4().hex[:8]}")
    project_b = make_project(slug=f"b-{uuid.uuid4().hex[:8]}")
    db_session.add_all([project_a, project_b])
    await db_session.flush()

    repo = TestCaseRepository(db_session)
    a_case = await repo.add(make_test_case(project_a.id, type=TestType.SMOKE))
    b_case = await repo.add(make_test_case(project_b.id, type=TestType.EDGE))

    a_rows = await repo.list(project_a.id)
    assert [c.id for c in a_rows] == [a_case.id]
    assert all(c.project_id == project_a.id for c in a_rows)
    assert await repo.count(project_a.id) == 1
    assert await repo.count(project_b.id) == 1

    # Cross-tenant reads must not leak across the project boundary.
    assert await repo.get(project_a.id, b_case.id) is None
    assert await repo.get(project_b.id, a_case.id) is None
    assert await repo.list_by_type(project_a.id, TestType.EDGE) == []

    # Mutations are scoped too: A cannot delete B's row.
    assert await repo.delete(project_a.id, b_case.id) is False
    assert await repo.get(project_b.id, b_case.id) is not None
