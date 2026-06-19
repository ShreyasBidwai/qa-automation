"""Mode C, step 3 — generate E2E cases from a journey, persisted as PROPOSALS.

Reuses the EXISTING T4.4 e2e_generator unchanged: it builds the deterministic
plan, enforces the mutation-kill gate, AI-renders the spec, and persists through
the T3.2 CaseMergeService (idempotent-by-case_key, never clobbering a human
edit). Mode-C cases are PROPOSALS the human asked for, so net-new/updated cases
are re-tagged ``origin=proposed`` + ``proposal_status=pending`` (a re-gen that
hits a human-edited case is ALREADY a non-current proposal from the merge engine
and is left exactly as-is — the human version is never touched). See ADR-0019.

Per the Sprint-5 coordination contract this is a NEW file that calls the shared
generator/merge components without modifying them.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.e2e_generator import E2EGenerator, GeneratedE2ECase
from app.models.enums import CaseOrigin, ProposalStatus

# Merge actions that created a fresh AI-owned current version — for Mode C these
# are re-tagged as proposals. "proposed" is left untouched (already a proposal).
_RETAG_ACTIONS = frozenset({"created", "updated"})


async def generate_proposed_cases(
    *,
    session: AsyncSession,
    project_id: uuid.UUID,
    page_node_id: uuid.UUID,
    generator: E2EGenerator,
) -> list[GeneratedE2ECase]:
    """Generate E2E cases for a page and persist them as Mode-C proposals.

    Returns the generated cases; new/updated ones now carry ``origin=proposed``
    and ``proposal_status=pending`` so they surface in the human review queue.
    """
    results = await generator.generate_and_persist(
        session=session, project_id=project_id, page_node_id=page_node_id
    )
    for result in results:
        if result.action in _RETAG_ACTIONS:
            result.test_case.origin = CaseOrigin.PROPOSED
            result.test_case.proposal_status = ProposalStatus.PENDING
    await session.flush()
    return results
