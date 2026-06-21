"""Repository for ``projects`` — the tenancy root (TRD §3).

Project is NOT project-scoped (it *is* the scope), so this is a standalone
repository. Reads exclude soft-deleted rows (ADR-0029) and, when an ``accessor_id``
is given, enforce ownership (ADR-0031): a project is accessible iff it is unowned
(NULL = legacy/shared) or owned by the accessor. ``accessor_id=None`` skips the
ownership filter for trusted internal callers (e.g. a background job acting on a
project the endpoint already authorized).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


def _accessible(accessor_id: uuid.UUID | None) -> ColumnElement[bool]:
    """The ownership predicate (ADR-0031): unowned OR owned by the accessor."""
    if accessor_id is None:
        return Project.deleted_at.is_(None)
    return Project.deleted_at.is_(None) & or_(
        Project.owner_id.is_(None), Project.owner_id == accessor_id
    )


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.flush()
        return project

    async def get(
        self, project_id: uuid.UUID, accessor_id: uuid.UUID | None = None
    ) -> Project | None:
        """A live, accessible project, or None (→ 404; existence not leaked)."""
        stmt = select(Project).where(
            Project.id == project_id, _accessible(accessor_id)
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def get_by_slug(self, slug: str) -> Project | None:
        stmt = select(Project).where(Project.slug == slug, Project.deleted_at.is_(None))
        return (await self.session.scalars(stmt)).one_or_none()

    async def list(
        self, *, limit: int, offset: int, accessor_id: uuid.UUID | None = None
    ) -> list[Project]:
        """A bounded page of accessible projects, newest first (deterministic)."""
        stmt = (
            select(Project)
            .where(_accessible(accessor_id))
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count(self, accessor_id: uuid.UUID | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(Project)
            .where(_accessible(accessor_id))
        )
        return int(await self.session.scalar(stmt) or 0)

    async def soft_delete(
        self, project_id: uuid.UUID, accessor_id: uuid.UUID | None = None
    ) -> bool:
        """Mark an accessible project deleted (ADR-0029). False if not accessible."""
        project = await self.get(project_id, accessor_id)
        if project is None:
            return False
        project.deleted_at = func.now()
        await self.session.flush()
        return True
