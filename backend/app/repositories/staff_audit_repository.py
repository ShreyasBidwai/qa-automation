"""Repository for ``staff_audit_log`` (ADR-0068).

Cross-tenant and append-only: staff actions are recorded, never mutated. A standalone
repository (like ``IncidentRepository``); access is gated at the API by staff RBAC.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff_audit_log import StaffAuditLog
from app.models.user import User


class StaffAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        actor: User,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> StaffAuditLog:
        """Append one immutable audit entry for a staff action (snapshots the actor
        email so the row stays identifiable if the account is later deleted)."""
        entry = StaffAuditLog(
            actor_id=actor.id,
            actor_email=actor.email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list(
        self,
        *,
        action: str | None = None,
        actor_id: uuid.UUID | None = None,
        limit: int,
        offset: int,
    ) -> list[StaffAuditLog]:
        """A newest-first page, optionally filtered by action and/or actor."""
        stmt = select(StaffAuditLog).order_by(
            StaffAuditLog.created_at.desc(), StaffAuditLog.id.desc()
        )
        if action is not None:
            stmt = stmt.where(StaffAuditLog.action == action)
        if actor_id is not None:
            stmt = stmt.where(StaffAuditLog.actor_id == actor_id)
        rows = await self.session.scalars(stmt.limit(limit).offset(offset))
        return list(rows.all())

    async def count(
        self,
        *,
        action: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(StaffAuditLog)
        if action is not None:
            stmt = stmt.where(StaffAuditLog.action == action)
        if actor_id is not None:
            stmt = stmt.where(StaffAuditLog.actor_id == actor_id)
        return int(await self.session.scalar(stmt) or 0)
