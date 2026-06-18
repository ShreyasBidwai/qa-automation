"""ProposalResolutionService — a human resolves a re-generation proposal (T3.3).

T3.2's merge engine, when a re-generation hits a human-edited case, appends a
NON-current ``origin=proposed``, ``proposal_status=pending`` version and leaves
the human's current version untouched (the clobber-protection; see
[[CaseMergeService]] / ADR-0012). This service is the human's decision on that
proposal:

- **accept** — adopt the regeneration: demote the human-edited current and
  promote the proposal to current. The human version is retained in history
  (never destroyed); "accept the regen" is not "delete my edit".
- **reject** — keep the edit: mark the proposal ``rejected`` and leave the
  human-edited current byte-for-byte untouched and still current. The rejected
  proposal stays as a dead, non-current version in history.

Resolution is terminal: a proposal that is already accepted/rejected cannot be
resolved again (``ProposalAlreadyResolvedError``). The exactly-one-current
invariant is enforced at the DB level (partial unique index, T3.1); accept hands
the pointer over in the order the index requires — demote first (zero current
rows), then promote (back to exactly one) — never two currents transiently.
Repositories do the project-scoped reads/writes (Standards §5).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CaseOrigin, ProposalStatus
from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository

from .errors import ProposalAlreadyResolvedError, TestCaseNotFoundError

logger = logging.getLogger("app.proposal_resolution")


class ProposalResolutionService:
    """Accept/reject pending re-generation proposals. All ops project-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TestCaseRepository(session)

    async def accept(
        self,
        project_id: uuid.UUID,
        lineage_id: uuid.UUID,
        proposal_version_id: uuid.UUID,
        accepted_by: str,
    ) -> TestCase:
        """Adopt the proposal: it becomes the lineage's current version.

        Demotes the existing (human-edited) current to non-current, then promotes
        the proposal — in that order, so the one-current partial unique index is
        never transiently violated. The demoted version is retained in history
        unchanged (only its ``is_current`` pointer flips); the human's edit is
        never destroyed. Records resolution provenance (``proposal_status=accepted``,
        ``resolved_by``, ``resolved_at``).

        Raises ``TestCaseNotFoundError`` if there is no such proposal in this
        project+lineage, and ``ProposalAlreadyResolvedError`` if it is no longer
        pending.
        """
        proposal = await self._load_pending(project_id, lineage_id, proposal_version_id)

        # Demote-then-promote: retire the current FIRST (now zero current rows),
        # then promote the proposal (back to exactly one). The retired row's
        # content is untouched — only the pointer flips, so the human edit
        # survives in history.
        current = await self._repo.get_current(project_id, lineage_id)
        if current is not None and current.id != proposal.id:
            current.is_current = False
            await self._session.flush()

        proposal.is_current = True
        self._mark_resolved(proposal, ProposalStatus.ACCEPTED, accepted_by)
        await self._session.flush()

        logger.info(
            "proposal.accepted",
            extra={
                "project_id": str(project_id),
                "lineage_id": str(lineage_id),
                "proposal_version_id": str(proposal_version_id),
                "version": proposal.version,
                "accepted_by": accepted_by,
            },
        )
        return proposal

    async def reject(
        self,
        project_id: uuid.UUID,
        lineage_id: uuid.UUID,
        proposal_version_id: uuid.UUID,
        rejected_by: str,
    ) -> TestCase:
        """Discard the proposal: keep the human edit as the current version.

        Marks the proposal ``rejected`` and records provenance; the proposal
        stays non-current (a dead version in history). The human-edited current
        is not touched at all — it remains current and byte-for-byte unchanged.

        Raises ``TestCaseNotFoundError`` / ``ProposalAlreadyResolvedError`` as
        for :meth:`accept`.
        """
        proposal = await self._load_pending(project_id, lineage_id, proposal_version_id)

        # No pointer flip: the proposal is already non-current and the human
        # current is left entirely alone. Only the proposal's lifecycle changes.
        self._mark_resolved(proposal, ProposalStatus.REJECTED, rejected_by)
        await self._session.flush()

        logger.info(
            "proposal.rejected",
            extra={
                "project_id": str(project_id),
                "lineage_id": str(lineage_id),
                "proposal_version_id": str(proposal_version_id),
                "version": proposal.version,
                "rejected_by": rejected_by,
            },
        )
        return proposal

    async def list_pending_proposals(self, project_id: uuid.UUID) -> list[TestCase]:
        """Pending proposals awaiting a human decision (project-scoped)."""
        return await self._repo.list_pending_proposals(project_id)

    async def _load_pending(
        self,
        project_id: uuid.UUID,
        lineage_id: uuid.UUID,
        proposal_version_id: uuid.UUID,
    ) -> TestCase:
        """Fetch a pending proposal or raise the appropriate typed error.

        Anything that is not a proposal of this project+lineage is "not found"
        (a non-proposal id has no proposal to resolve); a proposal that exists
        but is no longer pending is a terminal-state conflict.
        """
        proposal = await self._repo.get(project_id, proposal_version_id)
        if (
            proposal is None
            or proposal.lineage_id != lineage_id
            or proposal.origin is not CaseOrigin.PROPOSED
        ):
            raise TestCaseNotFoundError(
                f"no proposal {proposal_version_id} for lineage {lineage_id} "
                f"in project {project_id}"
            )
        if proposal.proposal_status is not ProposalStatus.PENDING:
            status = proposal.proposal_status
            raise ProposalAlreadyResolvedError(
                f"proposal {proposal_version_id} is not pending "
                f"(status={status.value if status else 'none'})"
            )
        return proposal

    @staticmethod
    def _mark_resolved(proposal: TestCase, status: ProposalStatus, actor: str) -> None:
        """Stamp the terminal status + resolution provenance on the proposal."""
        proposal.proposal_status = status
        proposal.resolved_by = actor
        proposal.resolved_at = datetime.now(UTC)
