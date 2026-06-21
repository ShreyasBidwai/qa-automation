"""Repository for ``organizations`` + ``organization_members`` (B3, ADR-0032).

The team aggregate: an org and who belongs to it with what role. Membership is the
access primitive — every data endpoint resolves access through it (ADR-0033).
Invites live in their own repository (``OrganizationInviteRepository``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- organizations -------------------------------------------------------

    async def add(self, organization: Organization) -> Organization:
        self.session.add(organization)
        await self.session.flush()
        return organization

    async def get(self, org_id: uuid.UUID) -> Organization | None:
        return await self.session.get(Organization, org_id)

    async def get_personal_org(self, user_id: uuid.UUID) -> Organization | None:
        """The user's auto-created solo workspace (ADR-0032) — `POST /projects`
        default target when no org is named."""
        stmt = (
            select(Organization)
            .join(
                OrganizationMember,
                OrganizationMember.org_id == Organization.id,
            )
            .where(
                OrganizationMember.user_id == user_id,
                Organization.is_personal.is_(True),
            )
            .order_by(Organization.created_at, Organization.id)
            .limit(1)
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def delete(self, org_id: uuid.UUID) -> None:
        """Hard-delete an org (owner action; cascades to its projects + members)."""
        await self.session.execute(
            delete(Organization).where(Organization.id == org_id)
        )
        await self.session.flush()

    # --- memberships ---------------------------------------------------------

    async def add_member(
        self, org_id: uuid.UUID, user_id: uuid.UUID, role: OrgRole
    ) -> OrganizationMember:
        member = OrganizationMember(org_id=org_id, user_id=user_id, role=role)
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_membership(
        self, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationMember | None:
        stmt = select(OrganizationMember).where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.user_id == user_id,
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def member_org_ids(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Every org the user belongs to (any role) — the VIEW scope for lists."""
        stmt = select(OrganizationMember.org_id).where(
            OrganizationMember.user_id == user_id
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_orgs_for_user(
        self, user_id: uuid.UUID
    ) -> list[tuple[Organization, OrgRole]]:
        """The user's orgs with their role in each (for `GET /orgs`)."""
        stmt = (
            select(Organization, OrganizationMember.role)
            .join(
                OrganizationMember,
                OrganizationMember.org_id == Organization.id,
            )
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at, Organization.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(org, role) for org, role in rows]

    async def list_members(
        self, org_id: uuid.UUID
    ) -> list[tuple[OrganizationMember, User]]:
        """Members of an org, each with their user record (email/name)."""
        stmt = (
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.org_id == org_id)
            .order_by(OrganizationMember.created_at, OrganizationMember.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(member, user) for member, user in rows]

    async def count_owners(self, org_id: uuid.UUID) -> int:
        """Number of owners — guards the "an org keeps ≥1 owner" rule (ADR-0033)."""
        stmt = (
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.role == OrgRole.OWNER,
            )
        )
        return int(await self.session.scalar(stmt) or 0)

    async def remove_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(OrganizationMember).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        await self.session.flush()
        return bool(result.rowcount)
