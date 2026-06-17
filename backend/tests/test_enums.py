"""Enum constraints — the database rejects values outside the TRD set."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project


async def test_invalid_enum_value_is_rejected(db_session: AsyncSession) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    # A savepoint isolates the expected failure so the session stays usable.
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO test_cases "
                    "(project_id, type, layer, oracle_source, authored_by) "
                    "VALUES (:pid, 'not-a-type', 'api', 'rule-derived', 'ai')"
                ),
                {"pid": project.id},
            )

    assert await TestCaseRepository(db_session).count(project.id) == 0
