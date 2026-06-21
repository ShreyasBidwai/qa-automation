"""Currently-open findings aggregation (ADR-0028) — the Findings inbox.

"Currently open" = each project's LATEST run, joined to triage, EXCLUDING
resolved / wont_fix / false_positive, deduped by ``root_cause_key`` (already unique
per run), ranked by severity. Soft-deleted projects (ADR-0029) are excluded.

Cross-project by design: the global inbox spans every project (single-tenant
pre-auth; tenancy lands in B2). The selection is the gated query — batched to a
fixed number of statements regardless of finding count (no N+1); the API enriches
the page to the run-dashboard detail shape via the existing FindingDetailReader,
grouped per ``(project, latest_run)``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TriageStatus
from app.models.finding import Finding
from app.models.finding_triage import FindingTriage
from app.models.project import Project
from app.models.run import Run

from .scoring import rank_key

# Dispositions that take an issue OUT of "currently open" (ADR-0027/0028).
_MUTED: frozenset[TriageStatus] = frozenset(
    {TriageStatus.RESOLVED, TriageStatus.WONT_FIX, TriageStatus.FALSE_POSITIVE}
)


class OpenFinding:
    """One open finding plus its triage record (None = untriaged → open)."""

    __slots__ = ("finding", "triage")

    def __init__(self, finding: Finding, triage: FindingTriage | None) -> None:
        self.finding = finding
        self.triage = triage


class OpenFindingsReader:
    """Reads the currently-open findings across (or within) projects (ADR-0028)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_run_ids(
        self, project_id: uuid.UUID | None, accessor_id: uuid.UUID | None = None
    ) -> list[uuid.UUID]:
        """The single most-recent run id per (live, accessible) project.

        One ``DISTINCT ON``. Scoped to one project when ``project_id`` is given,
        else all live projects; an ``accessor_id`` restricts to projects the user
        can access — unowned or owned by them (ADR-0031).
        """
        stmt = (
            select(Run.id)
            .join(Project, Project.id == Run.project_id)
            .where(Project.deleted_at.is_(None))
            .order_by(Run.project_id, Run.created_at.desc(), Run.id.desc())
            .distinct(Run.project_id)
        )
        if project_id is not None:
            stmt = stmt.where(Run.project_id == project_id)
        if accessor_id is not None:
            stmt = stmt.where(
                or_(Project.owner_id.is_(None), Project.owner_id == accessor_id)
            )
        return list((await self._session.scalars(stmt)).all())

    async def open_findings(
        self,
        project_id: uuid.UUID | None,
        *,
        limit: int,
        offset: int,
        accessor_id: uuid.UUID | None = None,
    ) -> tuple[list[OpenFinding], int]:
        """A severity-ranked page of currently-open findings + the total.

        Batched: one DISTINCT-ON for latest runs, one findings read, one triage
        read — constant statements regardless of finding count (no N+1). Scoped to
        the accessor's accessible projects when ``accessor_id`` is given.
        """
        run_ids = await self.latest_run_ids(project_id, accessor_id)
        if not run_ids:
            return [], 0

        findings = list(
            (
                await self._session.scalars(
                    select(Finding).where(Finding.run_id.in_(run_ids))
                )
            ).all()
        )
        if not findings:
            return [], 0

        triage = await self._triage_for(
            {(f.project_id, f.root_cause_key) for f in findings}
        )

        # Each (project, root_cause_key) is unique within its latest run (unique
        # index), so the set is already deduped; we only drop muted dispositions.
        open_items = [
            OpenFinding(f, triage.get((f.project_id, f.root_cause_key)))
            for f in findings
            if not _is_muted(triage.get((f.project_id, f.root_cause_key)))
        ]
        total = len(open_items)
        open_items.sort(key=lambda item: rank_key(item.finding))
        return open_items[offset : offset + limit], total

    async def _triage_for(
        self, pairs: set[tuple[uuid.UUID, str]]
    ) -> dict[tuple[uuid.UUID, str], FindingTriage]:
        """Triage records for many (project_id, root_cause_key) pairs in one query."""
        if not pairs:
            return {}
        stmt = select(FindingTriage).where(
            tuple_(FindingTriage.project_id, FindingTriage.root_cause_key).in_(
                list(pairs)
            )
        )
        rows = (await self._session.scalars(stmt)).all()
        return {(r.project_id, r.root_cause_key): r for r in rows}


def _is_muted(triage: FindingTriage | None) -> bool:
    return triage is not None and triage.status in _MUTED
