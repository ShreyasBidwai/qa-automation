"""Repository for ``projects`` — the tenancy root (TRD §3).

Project is NOT project-scoped (it *is* the scope), so this is a standalone
repository rather than a ``ProjectScopedRepository``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.flush()
        return project

    async def get(self, project_id: uuid.UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    async def get_by_slug(self, slug: str) -> Project | None:
        stmt = select(Project).where(Project.slug == slug)
        return (await self.session.scalars(stmt)).one_or_none()

    async def list(self, *, limit: int, offset: int) -> list[Project]:
        """A bounded page of projects, newest first (deterministic order)."""
        stmt = (
            select(Project)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(Project)
        return int(await self.session.scalar(stmt) or 0)
