"""Review a freshly-authored PROPOSED case — accept it, or discard it.

Mode C (UI/API) and CSV import author cases as PENDING proposals (``origin=proposed``)
so a human confirms before they run. This resolves ONE such proposal in place:

- **accept**  → ``proposal_status=accepted``; the case stays current and now runs.
- **discard** → ``proposal_status=rejected`` + ``is_current=False``; it drops out of
  the viewer and never runs (the row is kept for provenance, not destroyed).

Distinct from ``ProposalResolutionService`` (T3.3), which reconciles a RE-GENERATION
proposal against a human-EDITED current version (accept there demotes the edit). These
are net-new authored cases with no prior current, so review is a simple, safe status
transition — no lineage surgery. See ADR-0059.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProposalStatus
from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository


class CaseReviewError(Exception):
    """The case can't be reviewed (not found, or not a pending proposal)."""


class CaseReviewService:
    """Accept/discard a pending authored proposal. Project-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TestCaseRepository(session)

    async def _pending_case(
        self, project_id: uuid.UUID, case_id: uuid.UUID
    ) -> TestCase:
        case = (await self._repo.get_many(project_id, {case_id})).get(case_id)
        if case is None:
            raise CaseReviewError(f"test case {case_id} not found")
        # Idempotency + safety: only a live pending proposal is reviewable — an
        # already-accepted/rejected case (or a plain generated one) is never mutated.
        if not case.is_current or case.proposal_status is not ProposalStatus.PENDING:
            raise CaseReviewError("only a pending proposal can be reviewed")
        return case

    async def accept(
        self, project_id: uuid.UUID, case_id: uuid.UUID, *, reviewed_by: str
    ) -> TestCase:
        """Adopt the proposal: it stays current and runs from now on."""
        case = await self._pending_case(project_id, case_id)
        case.proposal_status = ProposalStatus.ACCEPTED
        case.resolved_by = reviewed_by
        case.resolved_at = datetime.now(UTC)
        await self._session.flush()
        return case

    async def discard(
        self, project_id: uuid.UUID, case_id: uuid.UUID, *, reviewed_by: str
    ) -> TestCase:
        """Reject the proposal: drop it from the viewer and never run it."""
        case = await self._pending_case(project_id, case_id)
        case.proposal_status = ProposalStatus.REJECTED
        # No longer current → excluded from the viewer (list_current) and from run
        # selection. The row survives for provenance; the lineage may have no current.
        case.is_current = False
        case.resolved_by = reviewed_by
        case.resolved_at = datetime.now(UTC)
        await self._session.flush()
        return case
