"""Repository for ``runs`` (TRD §3)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update

from app.models.project import Project
from app.models.run import Run

from .base import ProjectScopedRepository

# Run-status string vocabulary (the column is a free string owned by
# app.execution.lifecycle). Duplicated here as literals — NOT imported — because
# lifecycle imports this repo, so importing it back would be circular.
_STATUS_RUNNING = "running"
_STATUS_INTERRUPTED = "interrupted"


class RunRepository(ProjectScopedRepository[Run]):
    model = Run

    async def mark_interrupted(self, run_id: uuid.UUID) -> bool:
        """Compare-and-set a stale ``running`` run to ``interrupted`` (run-durability).

        Only flips a run STILL in ``running`` — it never clobbers a run that
        legitimately reached a terminal status (passed/failed/errored). Returns True
        iff it reconciled a row. The partial run + the cases committed before the
        crash survive; this just marks the orphaned row honestly.
        """
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status == _STATUS_RUNNING)
            .values(status=_STATUS_INTERRUPTED, finished_at=func.now())
            .returning(Run.id)
        )
        return (await self.session.scalar(stmt)) is not None

    async def interrupt_stale_running(self) -> list[uuid.UUID]:
        """Reconcile EVERY run still ``running`` to ``interrupted`` — the worker's
        startup sweep. A run left ``running`` when the worker (re)starts is orphaned
        by a crashed process (no live run is in flight at startup). Returns the ids
        reconciled. Compare-and-set on ``running`` so a concurrent legitimate finish
        is never clobbered.
        """
        stmt = (
            update(Run)
            .where(Run.status == _STATUS_RUNNING)
            .values(status=_STATUS_INTERRUPTED, finished_at=func.now())
            .returning(Run.id)
        )
        return list((await self.session.scalars(stmt)).all())

    async def next_run_number(self, project_id: uuid.UUID) -> int:
        """Atomically claim the next friendly run number for ``project_id`` (ADR-0048).

        ``UPDATE ... RETURNING`` increments the project's counter under a row lock, so
        two concurrent run creations always get distinct numbers (the
        ``(project_id, run_number)`` unique index is the backstop). The increment is
        part of the run's transaction — a run that rolls back frees its number, so
        failures leave no gap. Raises if the project does not exist.
        """
        stmt = (
            update(Project)
            .where(Project.id == project_id)
            .values(run_counter=Project.run_counter + 1)
            .returning(Project.run_counter)
        )
        number = await self.session.scalar(stmt)
        if number is None:
            raise ValueError(
                f"project {project_id} not found for run-number assignment"
            )
        return int(number)

    async def latest_run_per_project(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Run]:
        """The most-recent run per project, batched — ONE ``DISTINCT ON`` query.

        Same latest-run ordering as the open-findings reader (``created_at`` desc,
        ``id`` desc as the deterministic tiebreaker). Keyed by ``project_id``;
        projects with no runs are simply absent. Scoped to the passed ``project_ids``
        (the caller's already-authorized page) — no N+1 across projects.
        """
        ids = list(project_ids)
        if not ids:
            return {}
        stmt = (
            select(Run)
            .where(Run.project_id.in_(ids))
            .order_by(Run.project_id, Run.created_at.desc(), Run.id.desc())
            .distinct(Run.project_id)
        )
        return {run.project_id: run for run in (await self.session.scalars(stmt)).all()}

    async def list_for_projects(
        self,
        project_ids: Sequence[uuid.UUID],
        *,
        since: datetime | None = None,
        limit: int,
    ) -> list[Run]:
        """Runs ACROSS a set of projects, newest first, optionally only since ``since``.

        The account dashboard's cross-project feed (trend buckets + recent activity).
        ``project_ids`` are the caller's already-authorized (org-scoped) ids, so no RBAC
        is needed here; the bound caps a pathological account. One query, no N+1.
        """
        ids = list(project_ids)
        if not ids:
            return []
        stmt = select(Run).where(Run.project_id.in_(ids))
        if since is not None:
            stmt = stmt.where(Run.created_at >= since)
        stmt = stmt.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def list_for_project(
        self, project_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Run]:
        """A bounded page of a project's runs, newest first (deterministic)."""
        stmt = (
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Run).where(Run.project_id == project_id)
        return int(await self.session.scalar(stmt) or 0)

    async def prior_run_ids(
        self, project_id: uuid.UUID, run_id: uuid.UUID, *, limit: int
    ) -> list[uuid.UUID]:
        """The ``limit`` runs immediately before ``run_id``, oldest → newest.

        Ordered by ``(created_at, id)`` (deterministic); the bounded history window
        for cross-run classification (ADR-0023). Empty if the run is unknown or is
        the project's first.
        """
        current = await self.get(project_id, run_id)
        if current is None:
            return []
        before = or_(
            Run.created_at < current.created_at,
            and_(Run.created_at == current.created_at, Run.id < current.id),
        )
        stmt = (
            select(Run.id)
            .where(Run.project_id == project_id, before)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit)
        )
        recent_first = list((await self.session.scalars(stmt)).all())
        return list(reversed(recent_first))  # oldest → newest
