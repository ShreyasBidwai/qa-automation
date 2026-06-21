"""Repository for ``sessions`` (B2, ADR-0030) — server-side auth sessions."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_session import UserSession


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user_session: UserSession) -> UserSession:
        self.session.add(user_session)
        await self.session.flush()
        return user_session

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.token_hash == token_hash)
        return (await self.session.scalars(stmt)).one_or_none()

    async def delete_by_token_hash(self, token_hash: str) -> bool:
        """Revoke one session (sign-out). True if a row was deleted."""
        result = await self.session.execute(
            delete(UserSession).where(UserSession.token_hash == token_hash)
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def delete_for_user(self, user_id: uuid.UUID) -> int:
        """Revoke ALL of a user's sessions (e.g. after a password reset)."""
        result = await self.session.execute(
            delete(UserSession).where(UserSession.user_id == user_id)
        )
        await self.session.flush()
        return int(result.rowcount or 0)

    async def delete_for_user_except(
        self, user_id: uuid.UUID, keep_token_hash: str
    ) -> int:
        """Revoke a user's other sessions, keeping the current one (B3 password
        change): the caller stays signed in here while every other session dies."""
        result = await self.session.execute(
            delete(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.token_hash != keep_token_hash,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0)
