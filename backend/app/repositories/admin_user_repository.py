"""Cross-tenant admin repository for users (ADR-0068).

DELIBERATELY not tenant-scoped: staff queries span ALL users. Standalone, like
``AdminOrgRepository``. Reads the control-plane DB only (dual-DB rule); mutations are
limited to the staff-controllable fields — the account active flag and the staff role
— never a user's password, sessions, or any tenant data.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrgRole, StaffRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


class AdminUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _org_counts(self, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        stmt = (
            select(OrganizationMember.user_id, func.count())
            .where(OrganizationMember.user_id.in_(user_ids))
            .group_by(OrganizationMember.user_id)
        )
        return {uid: count for uid, count in (await self.session.execute(stmt))}

    async def list_users(
        self, *, search: str | None = None, limit: int, offset: int
    ) -> list[tuple[User, int]]:
        """A newest-first page of ALL users, each with its org-membership count.
        Optional case-insensitive email-substring filter."""
        stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
        if search:
            stmt = stmt.where(User.email.ilike(f"%{search}%"))
        rows = await self.session.scalars(stmt.limit(limit).offset(offset))
        users = list(rows.all())
        if not users:
            return []
        counts = await self._org_counts([user.id for user in users])
        return [(user, counts.get(user.id, 0)) for user in users]

    async def count_users(self, *, search: str | None = None) -> int:
        stmt = select(func.count()).select_from(User)
        if search:
            stmt = stmt.where(User.email.ilike(f"%{search}%"))
        return int(await self.session.scalar(stmt) or 0)

    async def get_with_orgs(
        self, user_id: uuid.UUID
    ) -> tuple[User, list[tuple[Organization, OrgRole]]] | None:
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        stmt = (
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at, Organization.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return user, [(org, role) for org, role in rows]

    async def set_active(self, user_id: uuid.UUID, *, active: bool) -> User | None:
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        user.is_active = active
        await self.session.flush()
        return user

    async def set_staff_role(
        self, user_id: uuid.UUID, *, role: StaffRole | None
    ) -> User | None:
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        user.staff_role = role
        await self.session.flush()
        return user
