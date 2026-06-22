"""Heal ↔ findings reconciliation (the additive step ADR-0040 flagged).

A LOCATION failure double-surfaces: B8 proposes a heal for it AND the assembler
turns the raw failing result into a Finding. Read together, that reads as "the app
is broken" when the honest story is "the test needs re-addressing". This reconciles
the two **at read time** (no new persistence): a finding is *superseded by a heal*
when its representative result's test case carries a proposed/confirmed heal in the
same run.

The link is the heal's existence, which is itself the confidence gate — B8 only
proposes a heal for a high-confidence LOCATION re-binding and NEVER for an assertion
failure. So an assertion finding can never be superseded (it has no heal), a
low-confidence location failure stays a finding (no heal proposed, surfaced
honestly), and a rejected heal un-supersedes its finding. Deterministic; two batched
queries regardless of finding count (no N+1).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding
from app.models.result import Result
from app.models.test_heal import STATUS_CONFIRMED, STATUS_PROPOSED, TestHeal

# A heal in one of these states masks its finding; a rejected heal does not (the
# human said "not a valid re-addressing" → the failure stands as a real finding).
_ACTIVE_HEAL_STATUSES = (STATUS_PROPOSED, STATUS_CONFIRMED)


async def superseded_finding_ids(
    session: AsyncSession, findings: Sequence[Finding]
) -> set[uuid.UUID]:
    """Ids of findings masked by an active heal on the same (run, test case).

    Two batched reads: representative result → test case, and the run's active
    heals. The result/run ids are taken from findings the caller is already
    authorised to see, so no separate tenancy filter is needed (mirrors the
    open-findings reader's by-id reads).
    """
    findings = list(findings)
    result_ids = {f.result_id for f in findings}
    run_ids = {f.run_id for f in findings}
    if not result_ids:
        return set()

    case_by_result = {
        result_id: test_case_id
        for result_id, test_case_id in (
            await session.execute(
                select(Result.id, Result.test_case_id).where(Result.id.in_(result_ids))
            )
        ).all()
    }
    healed_pairs = {
        (run_id, test_case_id)
        for run_id, test_case_id in (
            await session.execute(
                select(TestHeal.run_id, TestHeal.test_case_id).where(
                    TestHeal.run_id.in_(run_ids),
                    TestHeal.status.in_(_ACTIVE_HEAL_STATUSES),
                )
            )
        ).all()
    }
    return {
        finding.id
        for finding in findings
        if (finding.run_id, case_by_result.get(finding.result_id)) in healed_pairs
    }
