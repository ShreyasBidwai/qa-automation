"""Persist QA-authored CSV scenarios as versioned, runnable test cases.

Mirrors the AI generator's persistence path — render each row deterministically,
reconcile the whole set through the ``CaseMergeService`` (create / update, never a
blind write), and attach a script to whichever version the merge produced — but with
NO AI in the loop: the QA declared the tests, so rendering is pure and reproducible.
Idempotent: re-importing the same scenario updates its lineage in place (§Repositories).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.csv_import import (
    CsvRowError,
    csv_case_key,
    parse_csv_tests,
    render_csv_test,
    to_test_case,
    to_test_script,
)
from app.models.enums import AuthoredBy, CaseOrigin
from app.repositories.test_script_repository import TestScriptRepository
from app.services.case_merge_service import CaseMergeService


@dataclass(frozen=True)
class CsvImportResult:
    """Outcome of one CSV import (counts + the per-row problems the QA must fix)."""

    total: int  # scenarios that parsed cleanly and were persisted
    created: int
    updated: int
    errors: tuple[CsvRowError, ...]


class CsvTestImportService:
    """Turn a CSV of QA-declared scenarios into persisted, runnable test cases."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._merge = CaseMergeService(session)
        self._scripts = TestScriptRepository(session)

    async def import_csv(self, project_id: uuid.UUID, content: str) -> CsvImportResult:
        parsed = parse_csv_tests(content)
        if not parsed.specs:
            # Nothing valid to persist — surface the parse errors so the QA can fix
            # the file; a zero-row import is not a silent success.
            return CsvImportResult(total=0, created=0, updated=0, errors=parsed.errors)

        candidates = [
            to_test_case(project_id, spec, csv_case_key(spec)) for spec in parsed.specs
        ]
        outcomes = await self._merge.merge_all(project_id, candidates)

        created = 0
        updated = 0
        for spec, outcome in zip(parsed.specs, outcomes, strict=True):
            # The merge engine stamps every case it creates as AI-generated (its
            # design assumption). A CSV row is a HUMAN-authored test the QA specified
            # exactly, so re-stamp it honestly after the merge — mirroring how the
            # Mode-C paths re-tag their cases as proposals (ADR-0058 / ADR-0059).
            outcome.test_case.origin = CaseOrigin.AUTHORED
            outcome.test_case.authored_by = AuthoredBy.HUMAN
            await self._scripts.add(
                to_test_script(
                    project_id,
                    outcome.test_case.id,
                    render_csv_test(spec),
                    layer=spec.layer,
                )
            )
            if outcome.action == "created":
                created += 1
            else:  # "updated" (a re-import) — CSV keys never hit the "proposed" path
                updated += 1

        await self._session.flush()
        return CsvImportResult(
            total=len(parsed.specs),
            created=created,
            updated=updated,
            errors=parsed.errors,
        )
