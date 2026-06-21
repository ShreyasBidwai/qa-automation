"""OrgService — team/membership/invite business logic (B3, ADR-0032/0033).

Orchestrates the organization + invite + user repositories and the security
primitives + mailer. Routers stay thin: they authenticate, run the RBAC gate
(``app.api.authz``), and call into here. The two target-aware RBAC rules (only an
owner manages owners; an org keeps ≥1 owner) live here because they depend on the
*target's* role, not just the actor's. Invite tokens reuse B2's discipline: random,
hashed at rest, single-use, expiring, never logged or returned (ADR-0030/0033).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.organization_invite import OrganizationInvite
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.repositories.organization_invite_repository import (
    OrganizationInviteRepository,
)
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import normalize_email
from app.services.errors import (
    AlreadyMemberError,
    CannotDeletePersonalOrgError,
    InvalidInviteError,
    LastOwnerError,
    MemberNotFoundError,
    RoleManagementError,
)
from app.services.mailer import Mailer


class OrgService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        mailer: Mailer,
        invite_ttl_seconds: int,
    ) -> None:
        self._session = session
        self._orgs = OrganizationRepository(session)
        self._invites = OrganizationInviteRepository(session)
        self._users = UserRepository(session)
        self._mailer = mailer
        self._invite_ttl = invite_ttl_seconds

    async def create_org(self, name: str, owner: User) -> Organization:
        """Create a team and make the creator its owner."""
        org = await self._orgs.add(Organization(name=name, is_personal=False))
        await self._orgs.add_member(org.id, owner.id, OrgRole.OWNER)
        return org

    async def invite(
        self,
        *,
        org: Organization,
        actor_role: OrgRole,
        email: str,
        role: OrgRole,
        invited_by: uuid.UUID,
    ) -> OrganizationInvite:
        """Issue an emailed, single-use, expiring invite. Never returns the token.

        Only an owner may invite as ``owner`` (ADR-0033). Inviting an email whose
        account is already a member is a conflict.
        """
        email = normalize_email(email)
        if role == OrgRole.OWNER and actor_role != OrgRole.OWNER:
            raise RoleManagementError
        existing_user = await self._users.get_by_email(email)
        if (
            existing_user is not None
            and await self._orgs.get_membership(org.id, existing_user.id) is not None
        ):
            raise AlreadyMemberError
        token = generate_token()
        invite = await self._invites.add(
            OrganizationInvite(
                org_id=org.id,
                email=email,
                role=role,
                token_hash=hash_token(token),
                expires_at=self._now() + timedelta(seconds=self._invite_ttl),
                invited_by=invited_by,
            )
        )
        await self._mailer.send_org_invite(
            email=email, token=token, org_name=org.name, role=role.value
        )
        return invite

    async def accept_invite(self, token: str, user: User) -> OrganizationMember:
        """Consume an invite token and join ``user`` to the org with its role.

        Unknown / already-accepted / expired tokens fail uniformly. If the user is
        already a member, the token is still consumed (single-use) and the existing
        membership is returned.
        """
        record = await self._invites.get_by_token_hash(hash_token(token))
        if record is None or record.accepted_at is not None:
            raise InvalidInviteError
        if record.expires_at <= self._now():
            raise InvalidInviteError
        existing = await self._orgs.get_membership(record.org_id, user.id)
        if existing is not None:
            record.accepted_at = self._now()
            await self._session.flush()
            return existing
        member = await self._orgs.add_member(record.org_id, user.id, record.role)
        record.accepted_at = self._now()
        await self._session.flush()
        return member

    async def change_role(
        self,
        *,
        org_id: uuid.UUID,
        actor: OrganizationMember,
        target_user_id: uuid.UUID,
        new_role: OrgRole,
    ) -> OrganizationMember:
        """Change a member's role (ADR-0033 guards applied)."""
        target = await self._orgs.get_membership(org_id, target_user_id)
        if target is None:
            raise MemberNotFoundError
        self._guard_owner_management(actor, target, new_role)
        if (
            target.role == OrgRole.OWNER
            and new_role != OrgRole.OWNER
            and await self._orgs.count_owners(org_id) <= 1
        ):
            raise LastOwnerError
        target.role = new_role
        await self._session.flush()
        return target

    async def remove_member(
        self,
        *,
        org_id: uuid.UUID,
        actor: OrganizationMember,
        target_user_id: uuid.UUID,
    ) -> None:
        """Remove a member from the org (ADR-0033 guards applied)."""
        target = await self._orgs.get_membership(org_id, target_user_id)
        if target is None:
            raise MemberNotFoundError
        self._guard_owner_management(actor, target, None)
        if target.role == OrgRole.OWNER and await self._orgs.count_owners(org_id) <= 1:
            raise LastOwnerError
        await self._orgs.remove_member(org_id, target_user_id)

    async def delete_org(self, org: Organization) -> None:
        """Delete a team (owner action). Personal orgs cannot be deleted (ADR-0032)."""
        if org.is_personal:
            raise CannotDeletePersonalOrgError
        await self._orgs.delete(org.id)

    @staticmethod
    def _guard_owner_management(
        actor: OrganizationMember,
        target: OrganizationMember,
        new_role: OrgRole | None,
    ) -> None:
        """Only an owner may manage an owner or grant the owner role (ADR-0033)."""
        if actor.role != OrgRole.OWNER and (
            target.role == OrgRole.OWNER or new_role == OrgRole.OWNER
        ):
            raise RoleManagementError

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
