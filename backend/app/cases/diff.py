"""Deterministic, read-only structured diff between two test-case versions.

The TRD §3 versioning rule says re-generation "produces a sibling version but
must not supersede a human-edited head — it diffs and surfaces a merge, never
overwrites". This module is the *diff* half of that rule: given two immutable
``TestCase`` versions it computes a field-level, structure-aware difference so a
human (later, a UI in Sprint 6) can review a proposed regeneration against their
own edits. The re-generation merge engine (T3.3) consumes the result.

Properties this module guarantees:

- **Read-only.** It only reads version content; it performs no writes and owns
  no schema. Version lookups go through the existing T3.1 repository reads
  (``get_version``); no repository write method is added or changed.
- **Deterministic.** Dict keys are compared in sorted order and list elements by
  index, so the same two versions always produce byte-identical output — a
  hard requirement for a review artifact (Standards §15).
- **Typed errors.** Incomparable inputs raise an explicit domain error rather
  than silently producing a meaningless diff (Standards §7).

Only test *content* is compared (``COMPARED_FIELDS``). Identity, lineage, audit,
and provenance columns (``id``, ``version``, ``lineage_id``, ``authored_by``,
``edited_by_human``, ``created_at`` …) differ between any two versions by
construction, so including them would swamp the content diff with noise. The
compared set mirrors the human-editable content fields defined by T3.1.
"""

from __future__ import annotations

import enum
import json
import uuid
from dataclasses import dataclass
from typing import Any, Final

from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository
from app.services.errors import ServiceError, TestCaseNotFoundError

# The test-content fields compared between versions, in a fixed (deterministic)
# order. Mirrors the human-editable content set in TRD §3 versioning — these are
# the columns a regeneration or a human edit can legitimately change. Identity /
# lineage / audit / provenance columns are intentionally excluded (see module
# docstring): they always differ between two versions and are not "content".
COMPARED_FIELDS: Final[tuple[str, ...]] = (
    "type",
    "layer",
    "target_node",
    "preconditions",
    "steps",
    "expected",
    "oracle_source",
    "requirement_link",
    "status",
)


class CaseDiffError(ServiceError):
    """Base class for diff-layer failures (Standards §7 taxonomy)."""


class IncomparableVersionsError(CaseDiffError):
    """The two versions are not two versions of the *same* logical case.

    A diff is only meaningful within one lineage and one project — comparing
    versions across lineages (or across the tenancy boundary) is a caller bug,
    not an empty diff. Raised by :func:`diff` unless that guard is disabled.
    """


class ChangeType(str, enum.Enum):
    """How one field (or nested value) differs between the two versions."""

    UNCHANGED = "unchanged"
    CHANGED = "changed"
    ADDED = "added"  # present only in version B
    REMOVED = "removed"  # present only in version A


@dataclass(frozen=True)
class DiffEntry:
    """One node of the structured diff tree.

    ``path`` locates the value from the root: top-level entries are a single
    field name (e.g. ``("status",)``); nested entries append dict keys and list
    indices (e.g. ``("steps", 0, "action")``). Container nodes (dicts/lists)
    carry their child entries; leaf nodes carry ``old``/``new`` scalars. Values
    are *normalized* (enums → their value, UUIDs → str) so the tree is plain,
    comparable, JSON-serializable data.
    """

    path: tuple[str | int, ...]
    change: ChangeType
    old: Any = None
    new: Any = None
    children: tuple[DiffEntry, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """A plain, JSON-serializable view of this node and its children."""
        return {
            "path": list(self.path),
            "change": self.change.value,
            "old": self.old,
            "new": self.new,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass(frozen=True)
class CaseDiff:
    """The complete field-level diff of two test-case versions.

    ``fields`` has exactly one entry per :data:`COMPARED_FIELDS`, in that fixed
    order, each reporting ``unchanged | changed`` (top-level columns are always
    present, so they are never ``added``/``removed``; those statuses arise only
    inside nested dicts/lists). Use :meth:`changes` for the compact leaf view.
    """

    version_a: int
    version_b: int
    fields: tuple[DiffEntry, ...]

    @property
    def changed(self) -> bool:
        """True if any compared field differs between the versions."""
        return any(f.change is not ChangeType.UNCHANGED for f in self.fields)

    def changes(self) -> list[DiffEntry]:
        """The non-unchanged *leaf* changes, in deterministic document order.

        Container nodes are descended into rather than reported, so each entry
        is a concrete scalar change (``changed``) or a whole added/removed
        subtree — exactly what a reviewer or the merge engine acts on.
        """
        out: list[DiffEntry] = []
        for field_entry in self.fields:
            _collect_leaf_changes(field_entry, out)
        return out

    def to_dict(self) -> dict[str, Any]:
        """A plain, JSON-serializable view (for the UI / logs / T3.3)."""
        return {
            "version_a": self.version_a,
            "version_b": self.version_b,
            "changed": self.changed,
            "fields": [f.to_dict() for f in self.fields],
        }


def diff(
    version_a: TestCase,
    version_b: TestCase,
    *,
    require_same_lineage: bool = True,
) -> CaseDiff:
    """Structured, field-level diff of two test-case versions (read-only).

    Compares the test *content* of ``version_a`` (the baseline, e.g. a human's
    current edit) against ``version_b`` (e.g. a proposed regeneration), recursing
    into nested ``preconditions`` / ``steps`` / ``expected`` structures. Neither
    version is mutated.

    By default the two must belong to the same project and lineage (they are
    meant to be two versions of one logical case); pass
    ``require_same_lineage=False`` to diff arbitrary cases. Raises
    :class:`IncomparableVersionsError` when the guard fails.
    """
    if require_same_lineage and (
        version_a.project_id != version_b.project_id
        or version_a.lineage_id != version_b.lineage_id
    ):
        raise IncomparableVersionsError(
            "cannot diff versions of different lineages/projects: "
            f"a=(project={version_a.project_id}, lineage={version_a.lineage_id}) "
            f"b=(project={version_b.project_id}, lineage={version_b.lineage_id})"
        )

    fields = tuple(
        _diff_value(
            _normalize(getattr(version_a, name)),
            _normalize(getattr(version_b, name)),
            (name,),
        )
        for name in COMPARED_FIELDS
    )
    return CaseDiff(
        version_a=version_a.version,
        version_b=version_b.version,
        fields=fields,
    )


async def diff_versions(
    repo: TestCaseRepository,
    project_id: uuid.UUID,
    lineage_id: uuid.UUID,
    version_a: int,
    version_b: int,
) -> CaseDiff:
    """Read two versions of a lineage via the repository and diff them.

    Uses the existing T3.1 read ``get_version`` only (no writes). Raises
    :class:`~app.services.errors.TestCaseNotFoundError` if either version is
    missing in this project — the same typed error the version queries use, so
    the API boundary maps it to 404 uniformly.
    """
    a = await repo.get_version(project_id, lineage_id, version_a)
    if a is None:
        raise TestCaseNotFoundError(
            f"version {version_a} not found for lineage {lineage_id} "
            f"in project {project_id}"
        )
    b = await repo.get_version(project_id, lineage_id, version_b)
    if b is None:
        raise TestCaseNotFoundError(
            f"version {version_b} not found for lineage {lineage_id} "
            f"in project {project_id}"
        )
    return diff(a, b)


def render_diff(case_diff: CaseDiff) -> str:
    """Compact, deterministic text rendering of a diff for logs / CLI.

    One line per leaf change, prefixed by a sigil — ``~`` changed, ``+`` added,
    ``-`` removed — with a dotted/indexed path and JSON-encoded values. Returns
    ``"no changes"`` when the versions are identical in content.
    """
    lines: list[str] = []
    for entry in case_diff.changes():
        path = _render_path(entry.path)
        if entry.change is ChangeType.CHANGED:
            lines.append(f"~ {path}: {_fmt(entry.old)} -> {_fmt(entry.new)}")
        elif entry.change is ChangeType.ADDED:
            lines.append(f"+ {path}: {_fmt(entry.new)}")
        else:  # REMOVED
            lines.append(f"- {path}: {_fmt(entry.old)}")
    if not lines:
        return "no changes"
    return "\n".join(lines)


# --- internals ---------------------------------------------------------------


def _diff_value(old: Any, new: Any, path: tuple[str | int, ...]) -> DiffEntry:
    """Recursively diff two normalized values into a :class:`DiffEntry` tree."""
    if isinstance(old, dict) and isinstance(new, dict):
        children: list[DiffEntry] = []
        for key in sorted(set(old) | set(new)):
            child_path = (*path, key)
            if key in old and key in new:
                children.append(_diff_value(old[key], new[key], child_path))
            elif key in new:
                children.append(
                    DiffEntry(child_path, ChangeType.ADDED, old=None, new=new[key])
                )
            else:
                children.append(
                    DiffEntry(child_path, ChangeType.REMOVED, old=old[key], new=None)
                )
        return _container_entry(path, old, new, children)

    if isinstance(old, list) and isinstance(new, list):
        list_children: list[DiffEntry] = []
        for index in range(max(len(old), len(new))):
            child_path = (*path, index)
            if index < len(old) and index < len(new):
                list_children.append(_diff_value(old[index], new[index], child_path))
            elif index < len(new):
                list_children.append(
                    DiffEntry(child_path, ChangeType.ADDED, old=None, new=new[index])
                )
            else:
                list_children.append(
                    DiffEntry(child_path, ChangeType.REMOVED, old=old[index], new=None)
                )
        return _container_entry(path, old, new, list_children)

    # Scalars, or a structural type change (e.g. dict replaced by a scalar):
    # report the whole value as a single changed leaf.
    if old == new:
        return DiffEntry(path, ChangeType.UNCHANGED, old=old, new=new)
    return DiffEntry(path, ChangeType.CHANGED, old=old, new=new)


def _container_entry(
    path: tuple[str | int, ...],
    old: Any,
    new: Any,
    children: list[DiffEntry],
) -> DiffEntry:
    """Build a dict/list node; CHANGED iff any child differs."""
    change = (
        ChangeType.CHANGED
        if any(c.change is not ChangeType.UNCHANGED for c in children)
        else ChangeType.UNCHANGED
    )
    return DiffEntry(path, change, old=old, new=new, children=tuple(children))


def _collect_leaf_changes(entry: DiffEntry, out: list[DiffEntry]) -> None:
    """Append the non-unchanged leaf changes under ``entry`` to ``out``."""
    if entry.change is ChangeType.UNCHANGED:
        return
    if entry.children:
        for child in entry.children:
            _collect_leaf_changes(child, out)
    else:
        out.append(entry)


def _normalize(value: Any) -> Any:
    """Coerce a field value to plain, comparable, JSON-serializable data.

    Enums become their wire value and UUIDs their string form so that two
    versions compare on content (not Python identity) and the diff is directly
    serializable for the UI/logs. Dicts and lists are normalized recursively;
    primitives pass through unchanged.
    """
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize(v) for v in value]
    return value


def _render_path(path: tuple[str | int, ...]) -> str:
    """Render a path tuple as ``field.key[0].nested`` for the text diff."""
    out = ""
    for i, part in enumerate(path):
        if isinstance(part, int):
            out += f"[{part}]"
        elif i == 0:
            out += part
        else:
            out += f".{part}"
    return out


def _fmt(value: Any) -> str:
    """Compact, deterministic JSON encoding of a value for the text diff."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
