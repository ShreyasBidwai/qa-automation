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
from collections.abc import Sequence

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TriageStatus
from app.models.finding import Finding
from app.models.finding_triage import FindingTriage
from app.models.project import Project
from app.models.run import Run

from .heal_reconciliation import superseded_finding_ids
from .scoring import rank_key

# Dispositions that take an issue OUT of "currently open" (ADR-0027/0028).
_MUTED: frozenset[TriageStatus] = frozenset(
    {TriageStatus.RESOLVED, TriageStatus.WONT_FIX, TriageStatus.FALSE_POSITIVE}
)


class OpenFinding:
    """One open finding plus its triage record (None = untriaged → open).

    ``superseded`` marks a finding masked by an active heal (B8) — addressing drift,
    not a broken app. Such findings are dropped from the default inbox and only
    surface (tagged) when the caller opts in.
    """

    __slots__ = ("finding", "triage", "superseded")

    def __init__(
        self,
        finding: Finding,
        triage: FindingTriage | None,
        *,
        superseded: bool = False,
    ) -> None:
        self.finding = finding
        self.triage = triage
        self.superseded = superseded


class OpenFindingsReader:
    """Reads the currently-open findings across (or within) projects (ADR-0028)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_run_ids(
        self,
        project_id: uuid.UUID | None,
        org_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[uuid.UUID]:
        """The single most-recent run id per (live, in-scope) project.

        One ``DISTINCT ON``. Scoped to one project when ``project_id`` is given,
        else all live projects; ``org_ids`` restricts to projects in those orgs —
        the orgs the caller may VIEW (ADR-0032/0033). ``org_ids=None`` skips the
        org filter (trusted internal callers only).
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
        if org_ids is not None:
            stmt = stmt.where(Project.org_id.in_(org_ids))
        return list((await self._session.scalars(stmt)).all())

    async def open_findings(
        self,
        project_id: uuid.UUID | None,
        *,
        limit: int,
        offset: int,
        org_ids: Sequence[uuid.UUID] | None = None,
        include_superseded: bool = False,
    ) -> tuple[list[OpenFinding], int]:
        """A severity-ranked page of currently-open findings + the total.

        Batched: one DISTINCT-ON for latest runs, one findings read, one triage
        read, two heal-reconciliation reads — constant statements regardless of
        finding count (no N+1). Scoped to the caller's viewable orgs when
        ``org_ids`` is given (ADR-0033). Findings masked by an active heal
        (addressing drift) are dropped unless ``include_superseded`` is set, in
        which case they are returned tagged.
        """
        run_ids = await self.latest_run_ids(project_id, org_ids)
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
        superseded = await superseded_finding_ids(self._session, findings)

        # Each (project, root_cause_key) is unique within its latest run (unique
        # index), so the set is already deduped; we drop muted dispositions and —
        # unless asked to include them — heal-superseded addressing drift.
        open_items: list[OpenFinding] = []
        for finding in findings:
            if _is_muted(triage.get((finding.project_id, finding.root_cause_key))):
                continue
            is_superseded = finding.id in superseded
            if is_superseded and not include_superseded:
                continue
            open_items.append(
                OpenFinding(
                    finding,
                    triage.get((finding.project_id, finding.root_cause_key)),
                    superseded=is_superseded,
                )
            )
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
