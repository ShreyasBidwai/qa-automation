"""Versioning — new_version forks a row without mutating the prior (never-clobber)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_test_case


async def test_new_version_forks_without_mutating_prior(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    repo = TestCaseRepository(db_session)
    prior = await repo.add(
        make_test_case(project.id, status="active", steps=[{"do": "x"}])
    )
    assert prior.version == 1
    assert prior.parent_version_id is None
    assert prior.edited_by_human is False

    new = await repo.new_version(
        prior, edited_by_human=True, status="edited", steps=[{"do": "y"}]
    )
    assert new.id != prior.id
    assert new.version == 2
    assert new.parent_version_id == prior.id
    assert new.edited_by_human is True
    assert new.status == "edited"
    assert new.steps == [{"do": "y"}]
    # The fork stays in the prior's lineage and is non-current by default — the
    # helper never creates a second current row (the caller promotes it).
    assert new.lineage_id == prior.lineage_id
    assert new.is_current is False

    # The prior row in the database is untouched (still the sole current row).
    await db_session.refresh(prior)
    assert prior.version == 1
    assert prior.parent_version_id is None
    assert prior.edited_by_human is False
    assert prior.status == "active"
    assert prior.steps == [{"do": "x"}]
    assert prior.is_current is True

    assert await repo.count(project.id) == 2
