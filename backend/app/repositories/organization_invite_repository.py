"""Repository for ``organization_invites`` (B3) — single-use email invites.

Mirrors ``PasswordResetTokenRepository`` (B2): lookups are by the token's SHA-256
hash; the raw token never touches the database.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization_invite import OrganizationInvite


class OrganizationInviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, invite: OrganizationInvite) -> OrganizationInvite:
        self.session.add(invite)
        await self.session.flush()
        return invite

    async def get_by_token_hash(self, token_hash: str) -> OrganizationInvite | None:
        stmt = select(OrganizationInvite).where(
            OrganizationInvite.token_hash == token_hash
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def list_pending(self, org_id: uuid.UUID) -> list[OrganizationInvite]:
        """Not-yet-accepted invites for an org, newest first (expiry shown, not
        filtered — the UI can flag stale ones)."""
        stmt = (
            select(OrganizationInvite)
            .where(
                OrganizationInvite.org_id == org_id,
                OrganizationInvite.accepted_at.is_(None),
            )
            .order_by(
                OrganizationInvite.created_at.desc(), OrganizationInvite.id.desc()
            )
        )
        return list((await self.session.scalars(stmt)).all())
