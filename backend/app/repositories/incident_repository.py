"""Repository for ``incidents`` (dev-suite slice 1).

NOT project-scoped — incidents are a cross-tenant operator diagnostic log with a
nullable ``project_id`` (some failures have no project). A standalone repository
(like ``ProjectRepository``); access is gated at the API by the operator flag.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, incident: Incident) -> Incident:
        self.session.add(incident)
        await self.session.flush()
        return incident

    async def get(self, incident_id: uuid.UUID) -> Incident | None:
        stmt = select(Incident).where(Incident.id == incident_id)
        return (await self.session.scalars(stmt)).one_or_none()

    async def list(
        self,
        *,
        phase: str | None = None,
        project_id: uuid.UUID | None = None,
        limit: int,
        offset: int,
    ) -> list[Incident]:
        """A newest-first page, optionally filtered by phase and/or project."""
        stmt = select(Incident).order_by(Incident.created_at.desc(), Incident.id.desc())
        if phase is not None:
            stmt = stmt.where(Incident.phase == phase)
        if project_id is not None:
            stmt = stmt.where(Incident.project_id == project_id)
        stmt = stmt.limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all())

    async def count(
        self,
        *,
        phase: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Incident)
        if phase is not None:
            stmt = stmt.where(Incident.phase == phase)
        if project_id is not None:
            stmt = stmt.where(Incident.project_id == project_id)
        return int(await self.session.scalar(stmt) or 0)
