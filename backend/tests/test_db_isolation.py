"""Per-test transactional isolation guard (ADR-0042).

The suite runs single-process on one shared DB. Before isolation, anything a test
committed (e.g. an open finding) persisted into later tests' global reads —
``open_findings(None)`` would see another test's rows, flipping green/red by
co-residency. These tests pin the guarantee that closed it:

  - two tests each COMMIT an open finding (via the app's own sessionmaker, the exact
    path a request commits through) and assert the unscoped global reader sees ONLY
    that test's finding — proving committed rows don't leak across tests;
  - a row the API commits is visible to the direct ``db_session`` within the test —
    proving both fixtures share one connection/transaction (so the teardown rollback
    actually covers what the API committed).

If isolation regresses, the second leak test sees ``total == 2`` and fails.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FindingLayer, OracleSource, Outcome
from app.models.finding import Finding
from app.reporting.open_findings import OpenFindingsReader
from app.repositories.finding_repository import FindingRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case


async def _commit_open_finding(app: FastAPI, key: str) -> None:
    """Commit one open finding the way a request would — via app.state.sessionmaker."""
    async with app.state.sessionmaker() as session:
        project = make_project()
        session.add(project)
        await session.flush()
        run = await RunRepository(session).add(make_run(project.id))
        case = await TestCaseRepository(session).add(make_test_case(project.id))
        result = await ResultRepository(session).add(
            make_result(project.id, run.id, case.id, outcome=Outcome.FAIL)
        )
        await FindingRepository(session).add(
            Finding(
                project_id=project.id,
                run_id=run.id,
                result_id=result.id,
                root_cause_key=key,
                explains_count=1,
                title=f"finding {key}",
                layer=FindingLayer.API,
                oracle_source=OracleSource.RULE_DERIVED,
                confidence_mixed=False,
                expected={},
                location={},
                severity="major",
                status="new",
            )
        )
        await session.commit()


async def _global_open(app: FastAPI) -> tuple[set[str], int]:
    async with app.state.sessionmaker() as session:
        page, total = await OpenFindingsReader(session).open_findings(
            None, limit=100, offset=0
        )
    return {item.finding.root_cause_key for item in page}, total


async def test_committed_open_finding_is_isolated_a(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    _, app = app_client
    await _commit_open_finding(app, "ISOLATION_A#fail")
    keys, total = await _global_open(app)
    # Sees ONLY its own committed finding — no leak from any other test.
    assert keys == {"ISOLATION_A#fail"}
    assert total == 1


async def test_committed_open_finding_is_isolated_b(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    _, app = app_client
    await _commit_open_finding(app, "ISOLATION_B#fail")
    keys, total = await _global_open(app)
    # Without isolation this would also see ISOLATION_A#fail (total == 2) when run
    # after the A test; with it, the A commit was rolled back → exactly one.
    assert keys == {"ISOLATION_B#fail"}
    assert total == 1


async def test_api_commit_is_visible_to_direct_db_session(
    app_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    """The two fixtures share one connection: what the API commits, db_session sees."""
    _, app = app_client
    # Commit via the app's sessionmaker first, then read via the direct session.
    await _commit_open_finding(app, f"SHARE-{uuid.uuid4().hex[:8]}#fail")
    page, total = await OpenFindingsReader(db_session).open_findings(
        None, limit=100, offset=0
    )
    assert total == 1 and len(page) == 1  # the API's committed row is visible here
