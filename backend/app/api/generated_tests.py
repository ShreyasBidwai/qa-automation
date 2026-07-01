"""Generated-tests viewer (read-only) — the tests a project's runs produce.

Lists the project's CURRENT test cases with their runnable Pest/PHPUnit code, so a
QA operator can SEE what Polaris generated (target endpoint, happy/negative, oracle
source, framework) — closing the loop between "it generated tests" and "here they
are." Project-scoped, VIEW-gated, read-only (the viewer never mutates a case).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.repositories.node_repository import NodeRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository

from .authz import authorize_project
from .deps import CurrentUser, get_session
from .schemas import TestCaseListResponse, TestCaseSummary

router = APIRouter(prefix="/api/v1", tags=["tests"])


@router.get("/projects/{project_id}/tests", response_model=TestCaseListResponse)
async def list_project_tests(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TestCaseListResponse:
    """The project's current generated tests + their code (VIEW). Read-only."""
    await authorize_project(session, project_id, current_user, Permission.VIEW)

    case_repo = TestCaseRepository(session)
    cases = await case_repo.list_current(project_id, limit=limit, offset=offset)

    # Resolve the two joins in ONE batched query each (never N+1): the runnable
    # script per case, and the Brain node name each case targets.
    scripts = await TestScriptRepository(session).latest_by_case(
        project_id, [c.id for c in cases]
    )
    node_ids = {c.target_node for c in cases if c.target_node is not None}
    names = {
        node.id: node.name
        for node in await NodeRepository(session).get_many(project_id, node_ids)
    }

    items: list[TestCaseSummary] = []
    for case in cases:
        script = scripts.get(case.id)
        target = (
            (names.get(case.target_node) or "—")
            if case.target_node is not None
            else "—"
        )
        items.append(
            TestCaseSummary(
                id=case.id,
                target=target,
                type=case.type.value,
                layer=case.layer.value,
                oracle_source=case.oracle_source.value,
                framework=script.framework.value if script else "—",
                code=script.code if script else "",
                created_at=case.created_at,
            )
        )

    total = await case_repo.count_current(project_id)
    return TestCaseListResponse(items=items, total=total)
