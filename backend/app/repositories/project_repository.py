"""Repository for ``projects`` — the tenancy root (TRD §3).

Project is NOT project-scoped (it *is* the scope), so this is a standalone
repository. Reads exclude soft-deleted rows (ADR-0029). Access is org-based
(ADR-0032/0033): single-project access is decided by ``app.api.authz`` against the
caller's membership, so ``get``/``soft_delete`` are unscoped (the caller has already
been authorized); list/count are scoped to a set of ``org_ids`` (the orgs the user
can see) so a page only ever contains the caller's projects.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

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
        """A live project by id (soft-delete aware). Access is checked by authz."""
        stmt = select(Project).where(
            Project.id == project_id, Project.deleted_at.is_(None)
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def get_by_slug(self, slug: str) -> Project | None:
        stmt = select(Project).where(Project.slug == slug, Project.deleted_at.is_(None))
        return (await self.session.scalars(stmt)).one_or_none()

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        org_ids: Sequence[uuid.UUID],
    ) -> list[Project]:
        """A bounded page of live projects in ``org_ids``, newest first."""
        stmt = (
            select(Project)
            .where(Project.deleted_at.is_(None), Project.org_id.in_(org_ids))
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count(self, *, org_ids: Sequence[uuid.UUID]) -> int:
        stmt = (
            select(func.count())
            .select_from(Project)
            .where(Project.deleted_at.is_(None), Project.org_id.in_(org_ids))
        )
        return int(await self.session.scalar(stmt) or 0)

    async def soft_delete(self, project_id: uuid.UUID) -> bool:
        """Mark a live project deleted (ADR-0029). False if already gone. The
        caller must already be authorized (``authz.authorize_project``)."""
        project = await self.get(project_id)
        if project is None:
            return False
        project.deleted_at = func.now()
        await self.session.flush()
        return True
