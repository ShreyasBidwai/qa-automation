"""Repository for ``findings`` (T7.1) — project-scoped."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.models.finding import Finding

from .base import ProjectScopedRepository


class FindingRepository(ProjectScopedRepository[Finding]):
    model = Finding

    async def list_for_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[Finding]:
        """All findings for a run in deterministic order (project-scoped).

        Ordered by ``root_cause_key`` — a stable, content-derived key (ADR-0021),
        so the same run always lists its findings the same way (created_at/id are
        not deterministic across re-assembly).
        """
        stmt = (
            select(Finding)
            .where(Finding.project_id == project_id, Finding.run_id == run_id)
            .order_by(Finding.root_cause_key)
        )
        return list((await self.session.scalars(stmt)).all())

    async def run_ids_with_key(
        self,
        project_id: uuid.UUID,
        run_ids: Sequence[uuid.UUID],
        root_cause_key: str,
    ) -> set[uuid.UUID]:
        """Which of ``run_ids`` have a finding for ``root_cause_key`` (scoped).

        The presence signal for cross-run history (ADR-0023): a run not in the
        result set had no finding for that key — i.e. did not fail that way.
        """
        if not run_ids:
            return set()
        stmt = (
            select(Finding.run_id)
            .where(
                Finding.project_id == project_id,
                Finding.run_id.in_(run_ids),
                Finding.root_cause_key == root_cause_key,
            )
            .distinct()
        )
        return set((await self.session.scalars(stmt)).all())

    async def runs_by_key(
        self,
        project_id: uuid.UUID,
        run_ids: Sequence[uuid.UUID],
        keys: Sequence[str],
    ) -> dict[str, set[uuid.UUID]]:
        """For each of ``keys``, which of ``run_ids`` had a finding for it (scoped).

        The batched form of :meth:`run_ids_with_key` — one query covering every
        key in a run, so cross-run history for a whole run's findings carries no
        N+1. Keys absent from every run simply don't appear in the result.
        """
        key_set = set(keys)
        if not run_ids or not key_set:
            return {}
        stmt = (
            select(Finding.root_cause_key, Finding.run_id)
            .where(
                Finding.project_id == project_id,
                Finding.run_id.in_(run_ids),
                Finding.root_cause_key.in_(key_set),
            )
            .distinct()
        )
        out: dict[str, set[uuid.UUID]] = {}
        for key, run_id in (await self.session.execute(stmt)).all():
            out.setdefault(key, set()).add(run_id)
        return out
