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
        """A live (not soft-deleted) project, or None (ADR-0029).

        Every caller (get-project, create-run, ingest, triage, …) treats a
        soft-deleted project as absent → 404 with no per-call change.
        """
        stmt = select(Project).where(
            Project.id == project_id, Project.deleted_at.is_(None)
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def get_by_slug(self, slug: str) -> Project | None:
        stmt = select(Project).where(Project.slug == slug, Project.deleted_at.is_(None))
        return (await self.session.scalars(stmt)).one_or_none()

    async def list(self, *, limit: int, offset: int) -> list[Project]:
        """A bounded page of live projects, newest first (deterministic order)."""
        stmt = (
            select(Project)
            .where(Project.deleted_at.is_(None))
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Project)
            .where(Project.deleted_at.is_(None))
        )
        return int(await self.session.scalar(stmt) or 0)

    async def soft_delete(self, project_id: uuid.UUID) -> bool:
        """Mark a live project deleted (ADR-0029). False if absent/already gone."""
        project = await self.get(project_id)
        if project is None:
            return False
        project.deleted_at = func.now()
        await self.session.flush()
        return True
