"""CRUD through the project-scoped repositories (Standards §15)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Framework, Outcome, RunMode, TestType, Triage
from app.models.project import Project
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository
from tests.factories import (
    make_project,
    make_result,
    make_run,
    make_test_case,
    make_test_script,
)


async def _project(session: AsyncSession) -> Project:
    project = make_project()
    session.add(project)
    await session.flush()
    return project


async def test_test_case_crud(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    repo = TestCaseRepository(db_session)

    case = await repo.add(make_test_case(project.id, type=TestType.HAPPY))
    assert case.id is not None

    fetched = await repo.get(project.id, case.id)
    assert fetched is not None
    assert fetched.type == TestType.HAPPY
    assert await repo.count(project.id) == 1
    assert [c.id for c in await repo.list(project.id)] == [case.id]
    assert [c.id for c in await repo.list_by_type(project.id, TestType.HAPPY)] == [
        case.id
    ]
    assert await repo.list_by_type(project.id, TestType.SMOKE) == []

    assert await repo.delete(project.id, case.id) is True
    assert await repo.get(project.id, case.id) is None
    assert await repo.count(project.id) == 0


async def test_test_script_crud(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    case = await TestCaseRepository(db_session).add(make_test_case(project.id))
    repo = TestScriptRepository(db_session)

    script = await repo.add(
        make_test_script(project.id, case.id, framework=Framework.PLAYWRIGHT)
    )
    fetched = await repo.get(project.id, script.id)
    assert fetched is not None
    assert fetched.framework == Framework.PLAYWRIGHT
    assert fetched.deterministic is True
    assert [s.id for s in await repo.list_for_test_case(project.id, case.id)] == [
        script.id
    ]
    assert await repo.delete(project.id, script.id) is True


async def test_run_and_result_crud(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    case = await TestCaseRepository(db_session).add(make_test_case(project.id))
    run = await RunRepository(db_session).add(
        make_run(project.id, mode=RunMode.B, commit_sha="abc1234")
    )
    fetched_run = await RunRepository(db_session).get(project.id, run.id)
    assert fetched_run is not None
    assert fetched_run.mode == RunMode.B
    assert fetched_run.status == "pending"

    results = ResultRepository(db_session)
    result = await results.add(
        make_result(
            project.id, run.id, case.id, outcome=Outcome.FAIL, triage=Triage.FLAKY
        )
    )
    fetched = await results.get(project.id, result.id)
    assert fetched is not None
    assert fetched.outcome == Outcome.FAIL
    assert fetched.triage == Triage.FLAKY
    assert [r.id for r in await results.list_for_run(project.id, run.id)] == [
        result.id
    ]
    assert await results.delete(project.id, result.id) is True
