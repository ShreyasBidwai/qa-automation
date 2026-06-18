"""CaseMergeService — the persistence path for (re)generation (TRD §3, T3.2).

Generation no longer writes test cases directly. Every freshly generated case is
reconciled against existing lineages by its deterministic ``case_key`` so that
re-running generation is idempotent-by-key and **never overwrites a human edit**:

- no existing lineage            → create a fresh v1, current, ``origin=generated``;
- existing, current is AI-only   → append a new generated version and flip current
                                   (AI cases track the code; history preserved);
- existing, current is HUMAN-edited → append a NON-current ``origin=proposed``,
                                   ``proposal_status=pending`` version and leave
                                   the human-edited current UNTOUCHED. This is the
                                   clobber-protection. Accept/reject is T3.3.

The exactly-one-current invariant is enforced at the DB level (partial unique
index from T3.1); this service only hands the pointer over in the correct order.
Repositories do the project-scoped reads/writes (Standards §5).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuthoredBy, CaseOrigin, ProposalStatus
from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository

from .errors import MergeError

logger = logging.getLogger("app.case_merge")

MergeAction = Literal["created", "updated", "proposed"]

# Content fields carried from a generated candidate onto an appended version.
# Identity (case_key, lineage), provenance, and the current pointer are owned by
# the merge logic, not copied blindly.
_CONTENT_FIELDS: Final[tuple[str, ...]] = (
    "type",
    "layer",
    "target_node",
    "preconditions",
    "steps",
    "expected",
    "oracle_source",
)


@dataclass(frozen=True)
class MergeOutcome:
    """The result of reconciling one generated case against existing lineages."""

    action: MergeAction
    case_key: str
    test_case: TestCase  # the row this generation created / appended


def _content(candidate: TestCase) -> dict[str, Any]:
    return {field: getattr(candidate, field) for field in _CONTENT_FIELDS}


class CaseMergeService:
    """Reconcile freshly generated cases into versioned lineages. Project-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TestCaseRepository(session)

    async def merge(self, project_id: uuid.UUID, candidate: TestCase) -> MergeOutcome:
        """Reconcile one generated ``candidate`` (transient, AI-authored, keyed).

        Raises ``MergeError`` if the candidate has no ``case_key`` or the key
        resolves ambiguously.
        """
        case_key = candidate.case_key
        if not case_key:
            raise MergeError("generated candidate has no case_key to match on")

        try:
            existing = await self._repo.get_current_by_case_key(project_id, case_key)
        except MultipleResultsFound as exc:  # invariant violation — fail loud
            raise MergeError(
                f"case_key {case_key!r} matches multiple current lineages "
                f"in project {project_id}"
            ) from exc

        if existing is None:
            return await self._create_fresh(project_id, candidate, case_key)
        if not existing.edited_by_human:
            return await self._append_generated(existing, candidate, case_key)
        return await self._propose(existing, candidate, case_key)

    async def merge_all(
        self, project_id: uuid.UUID, candidates: list[TestCase]
    ) -> list[MergeOutcome]:
        """Reconcile a whole fresh generation set, in order.

        STALE handling: a lineage whose ``case_key`` no longer appears in this set
        is left untouched — stale-marking is a deliberate later follow-up (the
        same forward-only deferral as node deletion in T2.6); nothing is deleted.
        """
        outcomes = [await self.merge(project_id, c) for c in candidates]
        by_action: dict[str, int] = {}
        for outcome in outcomes:
            by_action[outcome.action] = by_action.get(outcome.action, 0) + 1
        logger.info(
            "case_merge.completed",
            extra={"project_id": str(project_id), "actions": by_action},
        )
        return outcomes

    async def _create_fresh(
        self, project_id: uuid.UUID, candidate: TestCase, case_key: str
    ) -> MergeOutcome:
        candidate.project_id = project_id
        candidate.case_key = case_key
        candidate.origin = CaseOrigin.GENERATED
        candidate.authored_by = AuthoredBy.AI
        candidate.edited_by_human = False
        candidate.is_current = True
        candidate.proposal_status = None
        await self._repo.add(candidate)  # version 1, fresh lineage (server default)
        return MergeOutcome("created", case_key, candidate)

    async def _append_generated(
        self, existing: TestCase, candidate: TestCase, case_key: str
    ) -> MergeOutcome:
        # Flip-then-insert so the partial unique index is never transiently
        # violated: retire the AI-only current, then append the new current.
        existing.is_current = False
        await self._session.flush()
        new_version = await self._repo.new_version(
            existing,
            **_content(candidate),
            origin=CaseOrigin.GENERATED,
            authored_by=AuthoredBy.AI,
            edited_by_human=False,
            edited_by=None,
            proposal_status=None,
            is_current=True,
        )
        return MergeOutcome("updated", case_key, new_version)

    async def _propose(
        self, existing: TestCase, candidate: TestCase, case_key: str
    ) -> MergeOutcome:
        # The human-edited current is NEVER touched: the proposal is appended as a
        # non-current pending version. No is_current flip — `existing` stays the
        # sole current row for the lineage. THIS is the clobber-protection.
        proposal = await self._repo.new_version(
            existing,
            **_content(candidate),
            origin=CaseOrigin.PROPOSED,
            proposal_status=ProposalStatus.PENDING,
            authored_by=AuthoredBy.AI,
            edited_by_human=False,
            edited_by=None,
            status="draft",
            is_current=False,
        )
        return MergeOutcome("proposed", case_key, proposal)
