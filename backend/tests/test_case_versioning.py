"""Case versioning — edit appends an immutable, current version (TRD §3).

Exercises TestCaseService: edits APPEND versions (history is append-only and
immutable), the single current-version pointer flips, provenance is complete,
forward-copy loses no data, the version queries behave, the one-current invariant
is enforced by the DB, and every operation is project-scoped.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuthoredBy, CaseOrigin, OracleSource, TestType
from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository
from app.services.errors import InvalidEditError, TestCaseNotFoundError
from app.services.test_case_service import TestCaseService
from tests.factories import make_project, make_test_case

# Content/provenance columns that an edit must leave byte-for-byte on the prior
# version. is_current (the pointer) and updated_at (audit) are deliberately
# excluded — they are allowed to change on the retired row.
_IMMUTABLE_FIELDS = (
    "id",
    "version",
    "parent_version_id",
    "lineage_id",
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
    "created_at",
)


def _snapshot(tc: TestCase) -> dict[str, Any]:
    return {f: copy.deepcopy(getattr(tc, f)) for f in _IMMUTABLE_FIELDS}


async def _make_root(
    session: AsyncSession, **overrides: Any
) -> tuple[uuid.UUID, TestCase]:
    """Create a project + a v1/current root case; return (project_id, root)."""
    project = make_project()
    session.add(project)
    await session.flush()
    repo = TestCaseRepository(session)
    root = await repo.add(make_test_case(project.id, **overrides))
    # Force a reload so server-defaulted columns (lineage_id, is_current,
    # created_at, …) are concrete before we snapshot/compare.
    await session.refresh(root)
    return project.id, root


async def test_edit_appends_new_version_and_prior_is_immutable(
    db_session: AsyncSession,
) -> None:
    project_id, root = await _make_root(
        db_session, status="active", steps=[{"do": "x"}]
    )
    assert root.version == 1
    assert root.is_current is True
    before = _snapshot(root)

    service = TestCaseService(db_session)
    new = await service.edit(
        project_id, root.lineage_id, {"steps": [{"do": "y"}]}, edited_by="alice"
    )

    # A new row was appended, not the old one mutated.
    assert new.id != root.id
    assert new.version == 2
    assert new.parent_version_id == root.id
    assert new.lineage_id == root.lineage_id

    # The prior version's content is byte-for-byte unchanged; only the pointer
    # (is_current) flipped to false — history is immutable.
    await db_session.refresh(root)
    assert _snapshot(root) == before
    assert root.is_current is False

    # Exactly one current version exists for the lineage.
    repo = TestCaseRepository(db_session)
    history = await repo.get_history(project_id, root.lineage_id)
    assert [c.is_current for c in history] == [False, True]
    assert sum(c.is_current for c in history) == 1


async def test_edit_sets_human_flag_and_complete_provenance(
    db_session: AsyncSession,
) -> None:
    project_id, root = await _make_root(
        db_session, authored_by=AuthoredBy.AI, origin=CaseOrigin.GENERATED
    )
    assert root.edited_by_human is False
    assert root.edited_by is None

    service = TestCaseService(db_session)
    new = await service.edit(
        project_id, root.lineage_id, {"status": "reviewed"}, edited_by="bob@datagrid"
    )

    assert new.edited_by_human is True
    assert new.origin is CaseOrigin.EDITED
    assert new.parent_version_id == root.id
    assert new.edited_by == "bob@datagrid"
    # The edit timestamp is the new row's own created_at (no separate column).
    assert new.created_at is not None


async def test_edit_forward_copies_unchanged_fields(
    db_session: AsyncSession,
) -> None:
    node = uuid.uuid4()
    project_id, root = await _make_root(
        db_session,
        type=TestType.NEGATIVE,
        target_node=node,
        preconditions={"auth": True},
        steps=[{"method": "POST"}],
        expected={"status": 422},
        oracle_source=OracleSource.SPEC_GROUNDED,
        requirement_link="JIRA-123",
        status="active",
    )

    service = TestCaseService(db_session)
    # Change only the steps (e.g. a tweaked payload lives inside steps).
    new = await service.edit(
        project_id, root.lineage_id, {"steps": [{"method": "PUT"}]}, edited_by="carol"
    )

    assert new.steps == [{"method": "PUT"}]  # the change applied
    # Everything not in `changes` carried over unchanged — no data loss.
    assert new.type is TestType.NEGATIVE
    assert new.target_node == node
    assert new.preconditions == {"auth": True}
    assert new.expected == {"status": 422}
    assert new.oracle_source is OracleSource.SPEC_GROUNDED  # preserved as-is
    assert new.requirement_link == "JIRA-123"
    assert new.status == "active"


async def test_edit_changing_oracle_is_honored(db_session: AsyncSession) -> None:
    project_id, root = await _make_root(
        db_session, oracle_source=OracleSource.CHARACTERIZATION
    )
    service = TestCaseService(db_session)
    new = await service.edit(
        project_id,
        root.lineage_id,
        {"oracle_source": OracleSource.SPEC_GROUNDED, "expected": {"status": 200}},
        edited_by="dana",
    )
    assert new.oracle_source is OracleSource.SPEC_GROUNDED
    assert new.expected == {"status": 200}


async def test_edit_rejects_non_editable_field(db_session: AsyncSession) -> None:
    project_id, root = await _make_root(db_session)
    service = TestCaseService(db_session)
    bad_changes: list[dict[str, Any]] = [
        {"version": 99},
        {"lineage_id": uuid.uuid4()},
        {"authored_by": "human"},
    ]
    for bad in bad_changes:
        with pytest.raises(InvalidEditError):
            await service.edit(project_id, root.lineage_id, bad, edited_by="eve")

    # The rejected edits made no changes — still a single v1/current row.
    repo = TestCaseRepository(db_session)
    history = await repo.get_history(project_id, root.lineage_id)
    assert [c.version for c in history] == [1]


async def test_queries_current_history_version(db_session: AsyncSession) -> None:
    project_id, root = await _make_root(db_session, status="v1")
    service = TestCaseService(db_session)
    await service.edit(project_id, root.lineage_id, {"status": "v2"}, edited_by="x")
    v3 = await service.edit(
        project_id, root.lineage_id, {"status": "v3"}, edited_by="x"
    )

    current = await service.get_current(project_id, root.lineage_id)
    assert current.id == v3.id
    assert current.version == 3
    assert current.status == "v3"

    history = await service.get_history(project_id, root.lineage_id)
    assert [c.version for c in history] == [1, 2, 3]  # oldest → newest
    assert [c.status for c in history] == ["v1", "v2", "v3"]

    assert (await service.get_version(project_id, root.lineage_id, 2)).status == "v2"

    with pytest.raises(TestCaseNotFoundError):
        await service.get_version(project_id, root.lineage_id, 99)
    with pytest.raises(TestCaseNotFoundError):
        await service.get_current(project_id, uuid.uuid4())


async def test_one_current_invariant_holds_and_db_rejects_second_current(
    db_session: AsyncSession,
) -> None:
    project_id, root = await _make_root(db_session, status="v1")
    service = TestCaseService(db_session)
    for n in range(2, 6):  # four more edits → versions 1..5
        await service.edit(
            project_id, root.lineage_id, {"status": f"v{n}"}, edited_by="x"
        )

    history = await service.get_history(project_id, root.lineage_id)
    assert [c.version for c in history] == [1, 2, 3, 4, 5]
    assert sum(c.is_current for c in history) == 1  # exactly one current
    assert history[-1].is_current is True

    # The invariant is enforced at the DB level: inserting a second current row
    # for the same (project_id, lineage_id) is rejected by the partial unique
    # index. A savepoint keeps the outer transaction usable after the failure.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                make_test_case(
                    project_id, lineage_id=root.lineage_id, is_current=True, version=99
                )
            )
            await db_session.flush()


async def test_ai_case_edited_becomes_human_current_with_ai_v1_preserved(
    db_session: AsyncSession,
) -> None:
    project_id, root = await _make_root(
        db_session,
        authored_by=AuthoredBy.AI,
        origin=CaseOrigin.GENERATED,
        steps=[{"ai": "generated"}],
    )
    assert root.authored_by is AuthoredBy.AI
    assert root.edited_by_human is False

    service = TestCaseService(db_session)
    edited = await service.edit(
        project_id, root.lineage_id, {"steps": [{"human": "tweak"}]}, edited_by="qa"
    )

    # The current version is now human-edited...
    assert edited.is_current is True
    assert edited.edited_by_human is True
    assert edited.origin is CaseOrigin.EDITED
    assert edited.steps == [{"human": "tweak"}]
    # ...while the AI v1 is preserved verbatim in history.
    history = await service.get_history(project_id, root.lineage_id)
    ai_v1 = history[0]
    assert ai_v1.version == 1
    assert ai_v1.authored_by is AuthoredBy.AI
    assert ai_v1.origin is CaseOrigin.GENERATED
    assert ai_v1.edited_by_human is False
    assert ai_v1.steps == [{"ai": "generated"}]
    assert ai_v1.is_current is False
    # authored_by records original authorship — carried forward, not rewritten.
    assert edited.authored_by is AuthoredBy.AI


async def test_tenancy_cannot_edit_or_read_other_project(
    db_session: AsyncSession,
) -> None:
    project_a, root = await _make_root(db_session, status="a-only")
    other = make_project()
    db_session.add(other)
    await db_session.flush()
    project_b = other.id

    service = TestCaseService(db_session)

    # Reads scoped to B never see A's lineage.
    with pytest.raises(TestCaseNotFoundError):
        await service.get_current(project_b, root.lineage_id)
    with pytest.raises(TestCaseNotFoundError):
        await service.get_history(project_b, root.lineage_id)
    with pytest.raises(TestCaseNotFoundError):
        await service.get_version(project_b, root.lineage_id, 1)

    # An edit issued under B cannot touch A's case.
    with pytest.raises(TestCaseNotFoundError):
        await service.edit(
            project_b, root.lineage_id, {"status": "hacked"}, edited_by="mallory"
        )

    # A's case is untouched: still a single v1/current row with its own value.
    history = await service.get_history(project_a, root.lineage_id)
    assert [c.version for c in history] == [1]
    assert history[0].status == "a-only"
    assert history[0].is_current is True
