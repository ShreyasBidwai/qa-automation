"""Structured version diff (T3.4) — deterministic, read-only field-level diff.

Most cases are pure (no DB): two in-memory ``TestCase`` objects exercise the
recursion, the per-field statuses, the text rendering, and determinism. One
DB-backed test exercises the real use case — an AI v1 vs a human-edited v2 read
back through the existing repository — plus the typed not-found error.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.diff import (
    ChangeType,
    DiffEntry,
    IncomparableVersionsError,
    diff,
    diff_versions,
    render_diff,
)
from app.models.enums import TestType
from app.repositories.test_case_repository import TestCaseRepository
from app.services.errors import TestCaseNotFoundError
from app.services.test_case_service import TestCaseService
from tests.factories import make_project, make_test_case

# Fixed identifiers keep the pure (no-DB) cases self-contained and deterministic.
_PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_LINEAGE = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _case(version: int, **overrides: Any) -> Any:
    """An in-memory TestCase in the shared (project, lineage), un-persisted."""
    return make_test_case(_PID, lineage_id=_LINEAGE, version=version, **overrides)


def _paths(case_diff: Any) -> list[tuple[str | int, ...]]:
    return [e.path for e in case_diff.changes()]


# --- pure structural cases ---------------------------------------------------


def test_identical_versions_produce_an_empty_diff() -> None:
    a = _case(1, status="active", steps=[{"do": "x"}], expected={"status": 200})
    b = _case(2, status="active", steps=[{"do": "x"}], expected={"status": 200})

    result = diff(a, b)

    assert result.changed is False
    assert result.changes() == []
    # Every compared field is reported, all as unchanged.
    assert all(f.change is ChangeType.UNCHANGED for f in result.fields)
    assert render_diff(result) == "no changes"


def test_changed_top_level_scalar_is_flagged_with_old_and_new() -> None:
    a = _case(1, status="draft")
    b = _case(2, status="active")

    changes = diff(a, b).changes()

    assert changes == [
        DiffEntry(("status",), ChangeType.CHANGED, old="draft", new="active")
    ]


def test_changed_enum_field_is_normalized_to_wire_values() -> None:
    a = _case(1, type=TestType.SMOKE)
    b = _case(2, type=TestType.HAPPY)

    (entry,) = diff(a, b).changes()

    assert entry.path == ("type",)
    assert entry.change is ChangeType.CHANGED
    assert entry.old == "smoke"
    assert entry.new == "happy"


def test_nested_change_in_expected_is_detected_at_leaf() -> None:
    a = _case(1, expected={"status": 201, "json": {"id": "*"}})
    b = _case(2, expected={"status": 200, "json": {"id": "*"}})

    changes = diff(a, b).changes()

    # Only the leaf that actually changed is reported; the unchanged sibling
    # (json.id) is not.
    assert changes == [
        DiffEntry(("expected", "status"), ChangeType.CHANGED, old=201, new=200)
    ]


def test_nested_change_in_steps_list_is_detected_by_index() -> None:
    a = _case(1, steps=[{"action": "click", "target": "#a"}])
    b = _case(2, steps=[{"action": "tap", "target": "#a"}])

    changes = diff(a, b).changes()

    assert changes == [
        DiffEntry(("steps", 0, "action"), ChangeType.CHANGED, old="click", new="tap")
    ]


def test_added_and_removed_nested_keys_are_detected() -> None:
    a = _case(1, expected={"status": 200}, preconditions={"auth": True})
    b = _case(2, expected={"status": 200, "body": {"ok": True}}, preconditions={})

    changes = diff(a, b).changes()
    by_path = {e.path: e for e in changes}

    assert by_path[("expected", "body")].change is ChangeType.ADDED
    assert by_path[("expected", "body")].new == {"ok": True}
    assert by_path[("expected", "body")].old is None

    assert by_path[("preconditions", "auth")].change is ChangeType.REMOVED
    assert by_path[("preconditions", "auth")].old is True
    assert by_path[("preconditions", "auth")].new is None


def test_appended_list_element_is_detected_as_added() -> None:
    a = _case(1, steps=[{"do": "x"}])
    b = _case(2, steps=[{"do": "x"}, {"do": "y"}])

    changes = diff(a, b).changes()

    assert changes == [
        DiffEntry(("steps", 1), ChangeType.ADDED, old=None, new={"do": "y"})
    ]


def test_removed_list_element_is_detected_as_removed() -> None:
    a = _case(1, steps=[{"do": "x"}, {"do": "y"}])
    b = _case(2, steps=[{"do": "x"}])

    changes = diff(a, b).changes()

    assert changes == [
        DiffEntry(("steps", 1), ChangeType.REMOVED, old={"do": "y"}, new=None)
    ]


def test_structural_type_change_is_a_single_changed_leaf() -> None:
    # expected.value goes from a scalar to a dict — reported wholesale, not
    # recursed into (the structure changed, not a field within it).
    a = _case(1, expected={"value": 5})
    b = _case(2, expected={"value": {"min": 1, "max": 9}})

    (entry,) = diff(a, b).changes()

    assert entry.path == ("expected", "value")
    assert entry.change is ChangeType.CHANGED
    assert entry.old == 5
    assert entry.new == {"min": 1, "max": 9}


# --- guards, rendering, determinism, serialization ---------------------------


def test_diff_across_lineages_raises_typed_error() -> None:
    a = _case(1)
    b = make_test_case(_PID, lineage_id=uuid.uuid4(), version=1)

    with pytest.raises(IncomparableVersionsError):
        diff(a, b)


def test_cross_lineage_diff_allowed_when_guard_disabled() -> None:
    a = _case(1, status="draft")
    b = make_test_case(_PID, lineage_id=uuid.uuid4(), version=1, status="active")

    result = diff(a, b, require_same_lineage=False)

    assert _paths(result) == [("status",)]


def test_render_diff_is_compact_and_ordered() -> None:
    a = _case(1, status="draft", expected={"status": 201}, preconditions={"auth": True})
    b = _case(
        2, status="active", expected={"status": 201, "body": "ok"}, preconditions={}
    )

    rendered = render_diff(diff(a, b))

    # Sigils: '-' removed, '+' added, '~' changed; ordered by COMPARED_FIELDS
    # (preconditions, then expected, then status), keys sorted within a dict.
    assert rendered == (
        "- preconditions.auth: true\n"
        '+ expected.body: "ok"\n'
        '~ status: "draft" -> "active"'
    )


def test_diff_is_deterministic_and_keys_sorted() -> None:
    # Insertion order deliberately reversed to prove output is key-sorted.
    a = _case(1, expected={"b": 1, "a": 2})
    b = _case(2, expected={"b": 9, "a": 8})

    first = diff(a, b)
    second = diff(a, b)

    assert first == second
    assert render_diff(first) == render_diff(second)
    # Deterministic order: 'a' before 'b' regardless of insertion order.
    assert _paths(first) == [("expected", "a"), ("expected", "b")]


def test_diff_is_json_serializable_including_uuids() -> None:
    node_a, node_b = uuid.uuid4(), uuid.uuid4()
    a = _case(1, target_node=node_a)
    b = _case(2, target_node=node_b)

    payload = diff(a, b).to_dict()

    # to_dict() round-trips through JSON (enums/UUIDs already normalized).
    restored = json.loads(json.dumps(payload))
    assert restored["changed"] is True
    target = next(f for f in restored["fields"] if f["path"] == ["target_node"])
    assert target["change"] == "changed"
    assert target["old"] == str(node_a)
    assert target["new"] == str(node_b)


# --- the real use case, read back through the repository ----------------------


async def _seed_v1(session: AsyncSession, **overrides: Any) -> tuple[uuid.UUID, Any]:
    """A project + a persisted, AI-authored v1 current case; returns (pid, v1)."""
    project = make_project()
    session.add(project)
    await session.flush()
    repo = TestCaseRepository(session)
    v1 = await repo.add(make_test_case(project.id, **overrides))
    await session.refresh(v1)  # concretize server defaults (lineage_id, version)
    return project.id, v1


async def test_diff_ai_v1_vs_human_edited_v2(db_session: AsyncSession) -> None:
    project_id, v1 = await _seed_v1(
        db_session,
        steps=[{"action": "call", "endpoint": "/users", "method": "POST"}],
        expected={"status": 201, "json": {"id": "*"}},
    )

    # A human edits the AI's case: changes the expected status and appends a step.
    # The edit appends an immutable v2 via the T3.1 service (never-clobber).
    service = TestCaseService(db_session)
    v2 = await service.edit(
        project_id,
        v1.lineage_id,
        {
            "expected": {"status": 200, "json": {"id": "*"}},
            "steps": [
                {"action": "call", "endpoint": "/users", "method": "POST"},
                {"action": "assert-db", "table": "users"},
            ],
        },
        edited_by="alice",
    )
    assert v2.version == 2

    repo = TestCaseRepository(db_session)
    result = await diff_versions(repo, project_id, v1.lineage_id, 1, 2)

    assert result.version_a == 1
    assert result.version_b == 2
    by_path = {e.path: e for e in result.changes()}
    assert by_path[("expected", "status")].change is ChangeType.CHANGED
    assert by_path[("expected", "status")].old == 201
    assert by_path[("expected", "status")].new == 200
    assert by_path[("steps", 1)].change is ChangeType.ADDED
    assert by_path[("steps", 1)].new == {"action": "assert-db", "table": "users"}

    # The diff is content-only: the edit flipped edited_by_human, but provenance
    # is excluded, so it never appears as a (noisy) change.
    rendered = render_diff(result)
    assert "edited_by_human" not in rendered
    assert "~ expected.status: 201 -> 200" in rendered


async def test_diff_versions_missing_version_raises_not_found(
    db_session: AsyncSession,
) -> None:
    project_id, v1 = await _seed_v1(db_session)
    repo = TestCaseRepository(db_session)

    # Missing on either side raises the same typed error.
    with pytest.raises(TestCaseNotFoundError):
        await diff_versions(repo, project_id, v1.lineage_id, 1, 99)
    with pytest.raises(TestCaseNotFoundError):
        await diff_versions(repo, project_id, v1.lineage_id, 99, 1)
