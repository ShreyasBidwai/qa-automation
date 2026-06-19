"""Repository for ``auth_challenge_log`` — append-only, project-scoped (T4.2a)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.auth_challenge_log import AuthChallengeLog

from .base import ProjectScopedRepository


class AuthChallengeLogRepository(ProjectScopedRepository[AuthChallengeLog]):
    model = AuthChallengeLog

    async def append(self, row: AuthChallengeLog) -> AuthChallengeLog:
        """Insert one challenge-encounter record (append-only — never updated)."""
        return await self.add(row)

    async def list_for_project(self, project_id: uuid.UUID) -> list[AuthChallengeLog]:
        """All challenge records for a project, oldest → newest (the analysis set)."""
        stmt = (
            select(AuthChallengeLog)
            .where(AuthChallengeLog.project_id == project_id)
            .order_by(AuthChallengeLog.created_at, AuthChallengeLog.id)
        )
        return list((await self.session.scalars(stmt)).all())
