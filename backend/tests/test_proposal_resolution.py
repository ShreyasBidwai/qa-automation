"""Proposal resolution — a human accepts/rejects a re-generation proposal (T3.3).

Builds the real scenario through the existing services: an AI v1, a human edit
(v2, current), then a re-generation that the merge engine lands as a non-current
pending proposal (v3). Then exercises ProposalResolutionService:

- accept promotes the proposal to current, demotes-but-retains the human version,
  records provenance, and keeps exactly one current;
- reject marks the proposal rejected and leaves the human current byte-for-byte
  untouched and still current;
- list_pending_proposals returns only pending, project-scoped;
- re-resolving a resolved proposal is terminal;
- the T3.4 diff composes to show what a proposal would change;
- everything is project-scoped.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.diff import diff
from app.models.enums import CaseOrigin, ProposalStatus
from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository
from app.services.case_merge_service import CaseMergeService
from app.services.errors import ProposalAlreadyResolvedError, TestCaseNotFoundError
from app.services.proposal_resolution_service import ProposalResolutionService
from app.services.test_case_service import TestCaseService
from tests.factories import make_project, make_test_case

# Every column — used to prove a row is byte-for-byte unchanged. Within one test
# transaction now() is constant, so created_at/updated_at do not drift; comparing
# them is meaningful (an unexpected new row or mutation would still differ).
_ALL_FIELDS = (
    "id",
    "project_id",
    "lineage_id",
    "parent_version_id",
    "version",
    "type",
    "layer",
    "target_node",
    "preconditions",
    "steps",
    "expected",
    "oracle_source",
    "authored_by",
    "edited_by_human",
    "requirement_link",
    "status",
    "origin",
    "edited_by",
    "case_key",
    "proposal_status",
    "resolved_by",
    "resolved_at",
    "is_current",
    "created_at",
    "updated_at",
)


def _snapshot(tc: TestCase, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    return {f: copy.deepcopy(getattr(tc, f)) for f in _ALL_FIELDS if f not in exclude}


async def _proposal_scenario(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    key: str = "POST /api/x::happy::h",
) -> tuple[uuid.UUID, uuid.UUID, TestCase, TestCase]:
    """Create AI v1 → human v2 (current) → pending proposal v3.

    Returns (project_id, lineage_id, human_current_v2, proposal_v3). The proposal
    is created through the real merge engine, so the setup mirrors production.
    """
    if project_id is None:
        project = make_project()
        session.add(project)
        await session.flush()
        project_id = project.id

    repo = TestCaseRepository(session)
    v1 = await repo.add(
        make_test_case(
            project_id, case_key=key, steps=[{"v": 1}], expected={"status": 201}
        )
    )
    await session.refresh(v1)
    lineage_id = v1.lineage_id

    v2 = await TestCaseService(session).edit(
        project_id,
        lineage_id,
        {"steps": [{"human": "edit"}], "status": "active"},
        edited_by="alice",
    )
    await session.refresh(v2)

    candidate = make_test_case(
        project_id, case_key=key, steps=[{"ai": "regen"}], expected={"status": 200}
    )
    outcome = await CaseMergeService(session).merge(project_id, candidate)
    assert outcome.action == "proposed"
    proposal = outcome.test_case
    await session.refresh(proposal)
    return project_id, lineage_id, v2, proposal


# --- accept ------------------------------------------------------------------


async def test_accept_promotes_proposal_and_retains_human_version(
    db_session: AsyncSession,
) -> None:
    project_id, lineage_id, v2, proposal = await _proposal_scenario(db_session)
    human_before = _snapshot(v2)

    accepted = await ProposalResolutionService(db_session).accept(
        project_id, lineage_id, proposal.id, accepted_by="bob"
    )

    # The proposal itself becomes the current version, with resolution provenance.
    assert accepted.id == proposal.id
    assert accepted.is_current is True
    assert accepted.proposal_status is ProposalStatus.ACCEPTED
    assert accepted.resolved_by == "bob"
    assert accepted.resolved_at is not None
    # Accept adopts the regen — content stays the AI's, not flagged as a human edit.
    assert accepted.edited_by_human is False
    assert accepted.steps == [{"ai": "regen"}]

    history = await TestCaseRepository(db_session).get_history(project_id, lineage_id)
    assert [h.version for h in history] == [1, 2, 3]
    _, v2_after, proposal_after = history

    # The human edit is RETAINED in history — only its current pointer flipped.
    await db_session.refresh(v2_after)
    assert v2_after.is_current is False
    expected_human = {k: v for k, v in human_before.items() if k != "is_current"}
    assert _snapshot(v2_after, exclude=("is_current",)) == expected_human

    # Exactly one current version survives the handoff.
    assert sum(h.is_current for h in history) == 1
    assert proposal_after.is_current is True


# --- reject ------------------------------------------------------------------


async def test_reject_keeps_human_current_byte_for_byte(
    db_session: AsyncSession,
) -> None:
    project_id, lineage_id, v2, proposal = await _proposal_scenario(db_session)
    human_before = _snapshot(v2)

    rejected = await ProposalResolutionService(db_session).reject(
        project_id, lineage_id, proposal.id, rejected_by="bob"
    )

    assert rejected.proposal_status is ProposalStatus.REJECTED
    assert rejected.is_current is False  # stays a dead, non-current version
    assert rejected.resolved_by == "bob"
    assert rejected.resolved_at is not None

    # The human-edited current is untouched: still current and byte-for-byte equal.
    await db_session.refresh(v2)
    assert _snapshot(v2) == human_before
    assert v2.is_current is True

    history = await TestCaseRepository(db_session).get_history(project_id, lineage_id)
    assert sum(h.is_current for h in history) == 1


# --- list pending ------------------------------------------------------------


async def test_list_pending_proposals_only_pending_and_project_scoped(
    db_session: AsyncSession,
) -> None:
    proj_a, lin_a1, _, prop_a1 = await _proposal_scenario(db_session, key="k1")
    _, _, _, prop_a2 = await _proposal_scenario(db_session, project_id=proj_a, key="k2")
    proj_b, _, _, prop_b = await _proposal_scenario(db_session, key="k1")

    svc = ProposalResolutionService(db_session)
    # Resolve one of project A's proposals — it must drop out of the pending list.
    await svc.accept(proj_a, lin_a1, prop_a1.id, accepted_by="bob")

    pending_a = await svc.list_pending_proposals(proj_a)
    assert {p.id for p in pending_a} == {prop_a2.id}  # not the accepted, not B's
    assert all(
        p.origin is CaseOrigin.PROPOSED and p.proposal_status is ProposalStatus.PENDING
        for p in pending_a
    )

    # Project B sees only its own pending proposal (no cross-project bleed).
    pending_b = await svc.list_pending_proposals(proj_b)
    assert {p.id for p in pending_b} == {prop_b.id}


# --- terminal + typed errors -------------------------------------------------


async def test_resolving_a_resolved_proposal_is_terminal(
    db_session: AsyncSession,
) -> None:
    project_id, lineage_id, _, proposal = await _proposal_scenario(db_session)
    svc = ProposalResolutionService(db_session)
    await svc.accept(project_id, lineage_id, proposal.id, accepted_by="bob")

    # An accepted proposal can be neither re-accepted nor rejected.
    with pytest.raises(ProposalAlreadyResolvedError):
        await svc.accept(project_id, lineage_id, proposal.id, accepted_by="carol")
    with pytest.raises(ProposalAlreadyResolvedError):
        await svc.reject(project_id, lineage_id, proposal.id, rejected_by="carol")

    # A rejected proposal is equally terminal.
    _, lin2, _, prop2 = await _proposal_scenario(
        db_session, project_id=project_id, key="k2"
    )
    await svc.reject(project_id, lin2, prop2.id, rejected_by="bob")
    with pytest.raises(ProposalAlreadyResolvedError):
        await svc.reject(project_id, lin2, prop2.id, rejected_by="carol")


async def test_missing_or_foreign_proposal_raises_not_found(
    db_session: AsyncSession,
) -> None:
    project_id, lineage_id, v2, proposal = await _proposal_scenario(db_session)
    svc = ProposalResolutionService(db_session)

    # Unknown proposal id.
    with pytest.raises(TestCaseNotFoundError):
        await svc.accept(project_id, lineage_id, uuid.uuid4(), accepted_by="bob")
    # Real proposal, wrong lineage.
    with pytest.raises(TestCaseNotFoundError):
        await svc.accept(project_id, uuid.uuid4(), proposal.id, accepted_by="bob")
    # A real version id that is not a proposal (the human current) → not found.
    with pytest.raises(TestCaseNotFoundError):
        await svc.reject(project_id, lineage_id, v2.id, rejected_by="bob")
    # Cross-project: another project cannot resolve this proposal.
    other = make_project()
    db_session.add(other)
    await db_session.flush()
    with pytest.raises(TestCaseNotFoundError):
        await svc.accept(other.id, lineage_id, proposal.id, accepted_by="bob")
    # And the proposal is still pending — a failed resolve changed nothing.
    await db_session.refresh(proposal)
    assert proposal.proposal_status is ProposalStatus.PENDING


# --- composition with the T3.4 diff -----------------------------------------


async def test_diff_of_current_human_vs_pending_proposal(
    db_session: AsyncSession,
) -> None:
    project_id, lineage_id, v2, proposal = await _proposal_scenario(db_session)

    current = await TestCaseRepository(db_session).get_current(project_id, lineage_id)
    assert current is not None and current.id == v2.id

    result = diff(current, proposal)  # both versions of the same lineage

    assert result.changed is True
    paths = {entry.path for entry in result.changes()}
    # The proposal would replace the human's step and change the expected status.
    assert ("steps", 0, "ai") in paths  # AI regen's step key added
    assert ("steps", 0, "human") in paths  # human's step key removed
    assert ("expected", "status") in paths  # 201 -> 200
