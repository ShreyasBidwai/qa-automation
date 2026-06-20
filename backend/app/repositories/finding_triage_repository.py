"""Repository for ``finding_triage`` (ADR-0027) — project-scoped."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.enums import TriageStatus
from app.models.finding_triage import FindingTriage

from .base import ProjectScopedRepository


class FindingTriageRepository(ProjectScopedRepository[FindingTriage]):
    model = FindingTriage

    async def upsert(
        self,
        project_id: uuid.UUID,
        root_cause_key: str,
        *,
        status: TriageStatus,
        note: str | None,
    ) -> FindingTriage:
        """Set the disposition for a logical issue (idempotent, race-free).

        Keyed on ``(project_id, root_cause_key)`` (ADR-0027) via an atomic
        ``INSERT … ON CONFLICT DO UPDATE`` — one disposition per issue, no
        duplicates, no read-modify-write race. ``triaged_at`` is stamped on every
        write. The seam for actor attribution (Tier-2 auth) is here: one column +
        one parameter, no read-path change.
        """
        stmt = (
            pg_insert(FindingTriage)
            .values(
                project_id=project_id,
                root_cause_key=root_cause_key,
                status=status,
                note=note,
                triaged_at=func.now(),
            )
            .on_conflict_do_update(
                index_elements=["project_id", "root_cause_key"],
                set_={
                    "status": status,
                    "note": note,
                    "triaged_at": func.now(),
                    "updated_at": func.now(),
                },
            )
        )
        await self.session.execute(stmt)
        # Re-read the canonical row (ORM-hydrated). ``populate_existing`` refreshes
        # the identity-map object so a second upsert in the same session returns the
        # NEW values, not a cached row. One extra read on a single write; the batched
        # GET path (get_for_keys) stays a single query.
        select_stmt = (
            select(FindingTriage)
            .where(
                FindingTriage.project_id == project_id,
                FindingTriage.root_cause_key == root_cause_key,
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.scalars(select_stmt)).one()

    async def get_for_keys(
        self, project_id: uuid.UUID, root_cause_keys: Iterable[str]
    ) -> dict[str, FindingTriage]:
        """Triage records for many issue keys in one query, keyed by key (no N+1).

        The batched read that merges the triage block into a whole run's findings.
        Keys with no record simply don't appear (the caller defaults them to open).
        """
        keys = set(root_cause_keys)
        if not keys:
            return {}
        stmt = select(FindingTriage).where(
            FindingTriage.project_id == project_id,
            FindingTriage.root_cause_key.in_(keys),
        )
        rows = (await self.session.scalars(stmt)).all()
        return {row.root_cause_key: row for row in rows}
