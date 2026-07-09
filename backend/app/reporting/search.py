"""Global name search across projects/findings/runs — the ⌘K command palette
(ADR-0072).

Deterministic, indexed ``ILIKE`` (pg_trgm-backed, migration 0035) name lookup — NOT
semantic/embeddings search. The palette jumps to a *known* project, finding, or run
by name; it does not answer open questions, so it never touches the embedding
provider. Every query joins to ``projects`` and filters by the caller's viewable
``org_ids`` (ADR-0033), exactly like ``OpenFindingsReader`` and the account
dashboard — a row outside the caller's orgs is never returned.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding
from app.models.project import Project
from app.models.run import Run

# The client-chosen ``types`` filter is validated against this allow-list at the API
# boundary (never fed straight into a query) — CLAUDE.md's "validate any
# client-chosen mode against an allow-list" rule.
ALLOWED_TYPES: tuple[str, ...] = ("project", "finding", "run")

SearchResultType = Literal["project", "finding", "run"]


@dataclass(frozen=True, slots=True)
class SearchResult:
    type: SearchResultType
    id: uuid.UUID
    label: str
    subtitle: str | None
    url: str


class SearchReader:
    """Name search across the caller's viewable orgs (ADR-0033/ADR-0072)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        q: str,
        *,
        types: Sequence[str],
        limit: int,
        org_ids: Sequence[uuid.UUID],
    ) -> list[SearchResult]:
        """Up to ``limit`` rows per requested type, newest first.

        A blank query or an empty ``org_ids`` (a user in no org — shouldn't happen,
        every signup gets a personal org, but defensive) short-circuits to no rows
        rather than an unbounded ``ILIKE '%%'`` matching everything.
        """
        query = q.strip()
        if not query or not org_ids:
            return []
        pattern = f"%{query}%"
        results: list[SearchResult] = []
        if "project" in types:
            results.extend(await self._search_projects(pattern, limit, org_ids))
        if "finding" in types:
            results.extend(await self._search_findings(pattern, limit, org_ids))
        if "run" in types:
            results.extend(await self._search_runs(pattern, limit, org_ids))
        return results

    async def _search_projects(
        self, pattern: str, limit: int, org_ids: Sequence[uuid.UUID]
    ) -> list[SearchResult]:
        stmt = (
            select(Project)
            .where(
                Project.deleted_at.is_(None),
                Project.org_id.in_(org_ids),
                Project.name.ilike(pattern),
            )
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(limit)
        )
        rows = (await self._session.scalars(stmt)).all()
        return [
            SearchResult(
                type="project",
                id=project.id,
                label=project.name,
                subtitle=project.slug,
                url=f"/projects/{project.id}",
            )
            for project in rows
        ]

    async def _search_findings(
        self, pattern: str, limit: int, org_ids: Sequence[uuid.UUID]
    ) -> list[SearchResult]:
        stmt = (
            select(Finding, Project.name)
            .join(Project, Project.id == Finding.project_id)
            .where(
                Project.deleted_at.is_(None),
                Project.org_id.in_(org_ids),
                Finding.title.ilike(pattern),
            )
            .order_by(Finding.created_at.desc(), Finding.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            SearchResult(
                type="finding",
                id=finding.id,
                label=finding.title,
                subtitle=project_name,
                url=f"/findings/{finding.id}",
            )
            for finding, project_name in rows
        ]

    async def _search_runs(
        self, pattern: str, limit: int, org_ids: Sequence[uuid.UUID]
    ) -> list[SearchResult]:
        # A Run carries no free-text name of its own — match it via its project's
        # name, its commit sha, or its friendly run number, so "search a run by name"
        # reads honestly as "by the project it belongs to" (documented in ADR-0072).
        stmt = (
            select(Run, Project.name)
            .join(Project, Project.id == Run.project_id)
            .where(
                Project.deleted_at.is_(None),
                Project.org_id.in_(org_ids),
                or_(
                    Project.name.ilike(pattern),
                    Run.commit_sha.ilike(pattern),
                    cast(Run.run_number, String).ilike(pattern),
                ),
            )
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        results: list[SearchResult] = []
        for run, project_name in rows:
            number = (
                f"#{run.run_number}" if run.run_number is not None else str(run.id)[:8]
            )
            results.append(
                SearchResult(
                    type="run",
                    id=run.id,
                    label=f"Run {number} · {project_name}",
                    subtitle=run.status,
                    url=f"/runs/{run.id}/findings",
                )
            )
        return results
