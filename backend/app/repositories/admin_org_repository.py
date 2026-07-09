"""Cross-tenant admin repository for organizations (ADR-0068).

DELIBERATELY not tenant-scoped: staff queries span ALL orgs. Kept separate from
``OrganizationRepository`` (which is membership-scoped and the only authority inside a
tenant) so the cross-tenant surface is explicit and auditable. Reads the control-plane
DB only (dual-DB rule); the only mutation is staff suspension — never a tenant's data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.project import Project


class AdminOrgRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _member_counts(self, org_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        stmt = (
            select(OrganizationMember.org_id, func.count())
            .where(OrganizationMember.org_id.in_(org_ids))
            .group_by(OrganizationMember.org_id)
        )
        return {org_id: count for org_id, count in (await self.session.execute(stmt))}

    async def _project_counts(self, org_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        # Non-deleted projects only (projects.deleted_at is the soft-delete marker).
        stmt = (
            select(Project.org_id, func.count())
            .where(Project.org_id.in_(org_ids), Project.deleted_at.is_(None))
            .group_by(Project.org_id)
        )
        return {org_id: count for org_id, count in (await self.session.execute(stmt))}

    async def list_orgs(
        self, *, search: str | None = None, limit: int, offset: int
    ) -> list[tuple[Organization, int, int]]:
        """A newest-first page of ALL orgs, each with its member + (non-deleted)
        project count. Optional case-insensitive name-substring filter."""
        stmt = select(Organization).order_by(
            Organization.created_at.desc(), Organization.id.desc()
        )
        if search:
            stmt = stmt.where(Organization.name.ilike(f"%{search}%"))
        rows = await self.session.scalars(stmt.limit(limit).offset(offset))
        orgs = list(rows.all())
        if not orgs:
            return []
        ids = [org.id for org in orgs]
        members = await self._member_counts(ids)
        projects = await self._project_counts(ids)
        return [(org, members.get(org.id, 0), projects.get(org.id, 0)) for org in orgs]

    async def count_orgs(self, *, search: str | None = None) -> int:
        stmt = select(func.count()).select_from(Organization)
        if search:
            stmt = stmt.where(Organization.name.ilike(f"%{search}%"))
        return int(await self.session.scalar(stmt) or 0)

    async def get_with_counts(
        self, org_id: uuid.UUID
    ) -> tuple[Organization, int, int] | None:
        org = await self.session.get(Organization, org_id)
        if org is None:
            return None
        members = (await self._member_counts([org_id])).get(org_id, 0)
        projects = (await self._project_counts([org_id])).get(org_id, 0)
        return (org, members, projects)

    async def set_suspended(
        self, org_id: uuid.UUID, *, suspended: bool
    ) -> Organization | None:
        """Suspend (set ``suspended_at`` = now) or reactivate (clear it). Returns the
        org, or None if it does not exist. Reversible; touches no tenant data."""
        org = await self.session.get(Organization, org_id)
        if org is None:
            return None
        org.suspended_at = datetime.now(UTC) if suspended else None
        await self.session.flush()
        return org
