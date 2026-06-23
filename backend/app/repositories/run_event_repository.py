"""Repository for ``run_events`` — the run-progress log (ADR-0050).

A standalone repository (like ``IncidentRepository`` / ``AiUsageRepository``):
``run_events`` is an observability log keyed by ``run_id`` rather than a
project-scoped entity. Reads are ordered by ``seq`` (deterministic) and support a
cursor (``after_seq``) so the live stream can poll for only the events it has not
seen yet.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run_event import RunEvent


class RunEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_run(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        after_seq: int | None = None,
    ) -> list[RunEvent]:
        """A run's events in ``seq`` order; only those after ``after_seq`` if given.

        Scoped by ``project_id`` as well as ``run_id`` (defence in depth — the caller
        has already authorized the run); the live stream passes ``after_seq`` as a
        cursor so each poll returns only newly-emitted events.
        """
        stmt = select(RunEvent).where(
            RunEvent.project_id == project_id,
            RunEvent.run_id == run_id,
        )
        if after_seq is not None:
            stmt = stmt.where(RunEvent.seq > after_seq)
        stmt = stmt.order_by(RunEvent.seq)
        return list((await self.session.scalars(stmt)).all())
