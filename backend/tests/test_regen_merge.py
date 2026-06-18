"""Re-generation merge — reconcile by stable key, never clobber a human edit (T3.2).

Drives the merge engine through the generator (StubAIProvider, no real model):
first generation creates fresh cases; re-gen of an AI-only case updates in place
(new generated version, current flips, history kept); re-gen of a human-edited
case yields a non-current pending proposal while the human version stays current
and byte-for-byte unchanged. Matching is by deterministic case_key, project-scoped.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.generation.case_key import compute_case_key
from app.generation.generator import TestGenerator
from app.generation.plan import plan_cases
from app.models.enums import AuthoredBy, CaseOrigin, ProposalStatus
from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository
from app.services.case_merge_service import CaseMergeService
from app.services.errors import MergeError
from app.services.test_case_service import TestCaseService
from tests.factories import make_project, make_test_case

# Every column — used to prove a human-edited row is byte-for-byte unchanged
# (including is_current and updated_at: the merge proposal must not touch it).
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
    "is_current",
    "created_at",
    "updated_at",
)


def _snapshot(tc: TestCase) -> dict[str, Any]:
    return {f: copy.deepcopy(getattr(tc, f)) for f in _ALL_FIELDS}


def _gen() -> TestGenerator:
    return TestGenerator(
        provider=StubAIProvider(), budget_tokens=4096, generated_by="stub"
    )


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


# --- 1. stable key ----------------------------------------------------------


def test_case_key_is_deterministic(endpoint_spec: object) -> None:
    cases = plan_cases(endpoint_spec)  # type: ignore[arg-type]
    keys1 = [compute_case_key(endpoint_spec, c) for c in cases]  # type: ignore[arg-type]
    keys2 = [compute_case_key(endpoint_spec, c) for c in cases]  # type: ignore[arg-type]

    assert keys1 == keys2  # same plan → same keys across runs
    assert len(set(keys1)) == len(keys1)  # every logical case has a distinct key

    by_name = {c.name: c for c in cases}
    email = compute_case_key(endpoint_spec, by_name["email_required_missing"])  # type: ignore[arg-type]
    name = compute_case_key(endpoint_spec, by_name["name_required_missing"])  # type: ignore[arg-type]
    assert email != name  # different field → different key
    assert email == "POST /api/users::negative::email_required_missing"
    assert compute_case_key(  # different rule (same endpoint) → different key
        endpoint_spec,  # type: ignore[arg-type]
        by_name["age_min_boundary"],
    ) != compute_case_key(
        endpoint_spec, by_name["age_max_boundary"]
    )  # type: ignore[arg-type]


# --- 2. first generation creates fresh --------------------------------------


async def test_first_generation_creates_fresh_current_generated(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project_id = await _project(db_session)
    results = await _gen().generate_and_persist(
        session=db_session, project_id=project_id, spec=endpoint_spec  # type: ignore[arg-type]
    )
    assert results
    assert all(r.action == "created" for r in results)

    cases = await TestCaseRepository(db_session).list(project_id)
    assert len(cases) == 14
    for tc in cases:
        assert tc.version == 1
        assert tc.is_current is True
        assert tc.origin is CaseOrigin.GENERATED
        assert tc.edited_by_human is False
        assert tc.authored_by is AuthoredBy.AI
        assert tc.case_key  # keyed
        assert tc.proposal_status is None
    assert len({tc.lineage_id for tc in cases}) == 14  # one lineage per case
    assert len({tc.case_key for tc in cases}) == 14


# --- 3. re-gen of an AI-only case updates in place ---------------------------


async def test_regen_ai_only_appends_version_and_flips_current(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project_id = await _project(db_session)
    await _gen().generate_and_persist(
        session=db_session, project_id=project_id, spec=endpoint_spec  # type: ignore[arg-type]
    )
    results2 = await _gen().generate_and_persist(
        session=db_session, project_id=project_id, spec=endpoint_spec  # type: ignore[arg-type]
    )
    assert all(r.action == "updated" for r in results2)  # in-place update

    cases = await TestCaseRepository(db_session).list(project_id)
    assert len(cases) == 28  # 14 lineages × 2 versions
    lineages = {tc.lineage_id for tc in cases}
    assert len(lineages) == 14  # no duplicate lineages

    for lineage_id in lineages:
        versions = sorted(
            (tc for tc in cases if tc.lineage_id == lineage_id),
            key=lambda t: t.version,
        )
        assert [v.version for v in versions] == [1, 2]
        assert versions[0].is_current is False  # history preserved, demoted
        assert versions[1].is_current is True  # new generated version is current
        assert versions[1].origin is CaseOrigin.GENERATED
        assert sum(v.is_current for v in versions) == 1  # exactly one current


# --- 4. THE clobber-protection: re-gen of a human-edited case ---------------


async def test_regen_human_edited_yields_pending_proposal_and_keeps_current(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project_id = await _project(db_session)
    results1 = await _gen().generate_and_persist(
        session=db_session, project_id=project_id, spec=endpoint_spec  # type: ignore[arg-type]
    )
    target = next(r for r in results1 if r.plan.name == "happy")
    lineage_id = target.test_case.lineage_id
    case_key = target.test_case.case_key

    # A human edits the AI v1 → v2 human-edited current.
    service = TestCaseService(db_session)
    edited = await service.edit(
        project_id,
        lineage_id,
        {"steps": [{"human": "tweak"}], "status": "active"},
        edited_by="alice",
    )
    assert edited.version == 2
    assert edited.edited_by_human is True
    assert edited.is_current is True
    await db_session.refresh(edited)
    human_before = _snapshot(edited)

    # Re-generate the whole endpoint.
    results2 = await _gen().generate_and_persist(
        session=db_session, project_id=project_id, spec=endpoint_spec  # type: ignore[arg-type]
    )
    target2 = next(r for r in results2 if r.plan.name == "happy")
    assert target2.action == "proposed"  # the edited case becomes a proposal
    # Every other (AI-only) case still updates in place.
    assert all(r.action == "updated" for r in results2 if r.plan.name != "happy")

    history = await TestCaseRepository(db_session).get_history(project_id, lineage_id)
    assert [h.version for h in history] == [1, 2, 3]
    v1, v2, proposal = history

    # THE assertion: the human-edited current is byte-for-byte unchanged and is
    # still the single current version — re-generation did not clobber it.
    await db_session.refresh(v2)
    assert _snapshot(v2) == human_before
    assert v2.is_current is True
    assert sum(h.is_current for h in history) == 1

    # The re-generation landed as a non-current pending proposal instead.
    assert proposal.origin is CaseOrigin.PROPOSED
    assert proposal.proposal_status is ProposalStatus.PENDING
    assert proposal.is_current is False
    assert proposal.edited_by_human is False
    assert proposal.authored_by is AuthoredBy.AI
    assert proposal.parent_version_id == v2.id
    assert proposal.case_key == case_key
    assert proposal.steps != v2.steps  # carries the freshly generated content
    assert v1.origin is CaseOrigin.GENERATED  # the original AI v1, untouched


# --- 5. matching by key, no duplicate lineages ------------------------------


async def test_regen_matches_by_key_without_duplicating_lineages(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project_id = await _project(db_session)
    for _ in range(3):  # generate three times
        await _gen().generate_and_persist(
            session=db_session, project_id=project_id, spec=endpoint_spec  # type: ignore[arg-type]
        )
    cases = await TestCaseRepository(db_session).list(project_id)
    assert len(cases) == 42  # 14 lineages × 3 versions
    assert len({c.case_key for c in cases}) == 14  # same logical cases
    assert len({c.lineage_id for c in cases}) == 14  # matched, not duplicated


# --- 6. project-scoped throughout -------------------------------------------


async def test_merge_is_project_scoped(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    repo = TestCaseRepository(db_session)

    # Same spec in both projects → each gets its own 14 keyed lineages.
    await _gen().generate_and_persist(
        session=db_session, project_id=project_a, spec=endpoint_spec  # type: ignore[arg-type]
    )
    await _gen().generate_and_persist(
        session=db_session, project_id=project_b, spec=endpoint_spec  # type: ignore[arg-type]
    )
    a_cases = await repo.list(project_a)
    b_cases = await repo.list(project_b)
    assert len(a_cases) == 14 and len(b_cases) == 14
    # Identical key strings across projects, but matched per-project only.
    assert {c.case_key for c in a_cases} == {c.case_key for c in b_cases}

    # Re-gen in A matches A's lineages by key (not B's) — proves scoping: a
    # cross-project match would resolve two current rows and raise.
    results_a2 = await _gen().generate_and_persist(
        session=db_session, project_id=project_a, spec=endpoint_spec  # type: ignore[arg-type]
    )
    assert all(r.action == "updated" for r in results_a2)
    assert len(await repo.list(project_a)) == 28  # A advanced to v2
    assert len(await repo.list(project_b)) == 14  # B untouched


# --- typed errors -----------------------------------------------------------


async def test_merge_rejects_candidate_without_case_key(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    candidate = make_test_case(project_id, case_key=None)
    with pytest.raises(MergeError):
        await CaseMergeService(db_session).merge(project_id, candidate)
