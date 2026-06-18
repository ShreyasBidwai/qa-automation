"""TestCaseService — versioned, editable test cases (TRD §3 never-clobber).

Owns the *policy* for editing a logical case so that re-generation can never
clobber human edits: every edit APPENDS a new immutable version, carries the
prior content forward (no data loss), records complete provenance, and flips the
single current-version pointer. Past versions are never mutated or deleted —
history is append-only. The exactly-one-current invariant is enforced at the DB
level (partial unique index); this service simply hands the pointer over in the
correct order. Repositories do the project-scoped reads/writes (Standards §5).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CaseOrigin
from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository

from .errors import InvalidEditError, TestCaseNotFoundError

logger = logging.getLogger("app.test_cases")

# The only columns a human edit may change: case *content*. Identity, lineage,
# audit, and provenance columns are owned by the service/DB and are off-limits
# (changing them would corrupt history or tenancy). authored_by is intentionally
# excluded — it records who originally authored the logical case and is carried
# forward unchanged; an edit is reflected via origin/edited_by/edited_by_human.
_EDITABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "type",
        "layer",
        "target_node",
        "preconditions",
        "steps",
        "expected",
        "oracle_source",
        "requirement_link",
        "status",
    }
)


class TestCaseService:
    """Edit + version queries for test cases. All operations are project-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TestCaseRepository(session)

    async def edit(
        self,
        project_id: uuid.UUID,
        lineage_id: uuid.UUID,
        changes: dict[str, Any],
        edited_by: str,
    ) -> TestCase:
        """Append a human-edited current version of a logical case.

        Forward-copies the current version's fields, applies ``changes`` (any
        editable case field — steps, payload, expected, oracle, …), and appends
        a NEW version. Never mutates a prior version's content: history is
        immutable. Sets ``edited_by_human=True`` and full provenance
        (``origin="edited"``, ``parent_version_id``, ``edited_by``, and the new
        row's ``created_at`` as the edit timestamp). ``oracle_source`` is carried
        forward as-is unless ``changes`` itself changes the oracle (a
        "human-vouched" oracle tier is a later refinement — not added now).

        Raises ``TestCaseNotFoundError`` if the lineage has no current version in
        this project, and ``InvalidEditError`` for any non-editable field.
        """
        unknown = set(changes) - _EDITABLE_FIELDS
        if unknown:
            raise InvalidEditError(
                f"non-editable field(s): {', '.join(sorted(unknown))}"
            )

        current = await self._repo.get_current(project_id, lineage_id)
        if current is None:
            raise TestCaseNotFoundError(
                f"no current version for lineage {lineage_id} in project {project_id}"
            )

        # Hand over the current-version pointer in the order the partial unique
        # index requires: retire the old current FIRST (now zero current rows),
        # then append the new current (back to exactly one). The prior row's
        # content is untouched — only the pointer flips.
        current.is_current = False
        await self._session.flush()

        new_version = await self._repo.new_version(
            current,
            **changes,
            is_current=True,
            edited_by_human=True,
            origin=CaseOrigin.EDITED,
            edited_by=edited_by,
        )

        logger.info(
            "test_case.edited",
            extra={
                "project_id": str(project_id),
                "lineage_id": str(lineage_id),
                "version": new_version.version,
                "changed_fields": sorted(changes),
            },
        )
        return new_version

    async def get_current(
        self, project_id: uuid.UUID, lineage_id: uuid.UUID
    ) -> TestCase:
        """The current version of a lineage. Raises if there is none (scoped)."""
        current = await self._repo.get_current(project_id, lineage_id)
        if current is None:
            raise TestCaseNotFoundError(
                f"no current version for lineage {lineage_id} in project {project_id}"
            )
        return current

    async def get_history(
        self, project_id: uuid.UUID, lineage_id: uuid.UUID
    ) -> list[TestCase]:
        """All versions of a lineage, oldest → newest. Raises if empty (scoped)."""
        history = await self._repo.get_history(project_id, lineage_id)
        if not history:
            raise TestCaseNotFoundError(
                f"no versions for lineage {lineage_id} in project {project_id}"
            )
        return history

    async def get_version(
        self, project_id: uuid.UUID, lineage_id: uuid.UUID, version: int
    ) -> TestCase:
        """One specific version of a lineage. Raises if absent (scoped)."""
        found = await self._repo.get_version(project_id, lineage_id, version)
        if found is None:
            raise TestCaseNotFoundError(
                f"version {version} not found for lineage {lineage_id} "
                f"in project {project_id}"
            )
        return found
