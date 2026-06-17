"""Schema-backed test exercising the test-DB fixture + factory (Standards §15)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from tests.factories import make_project


async def test_project_persists_with_defaults(db_session: AsyncSession) -> None:
    db_session.add(make_project(name="Loyalty", slug="loyalty"))
    await db_session.flush()

    row = (
        await db_session.execute(
            select(Project.id, Project.name, Project.settings).where(
                Project.slug == "loyalty"
            )
        )
    ).one()

    assert row.id is not None  # server-generated UUID
    assert row.name == "Loyalty"
    assert row.settings == {}  # jsonb server default
