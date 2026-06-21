"""Repository for ``users`` (B2). Standalone — users are an ownership root."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Look up by normalized email (callers lower-case before calling)."""
        stmt = select(User).where(User.email == email)
        return (await self.session.scalars(stmt)).one_or_none()
