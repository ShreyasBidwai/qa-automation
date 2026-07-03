"""Generated-tests viewer (read-only) — the tests a project's runs produce.

Lists the project's CURRENT test cases with their runnable Pest/PHPUnit code, so a
QA operator can SEE what Polaris generated (target endpoint, happy/negative, oracle
source, framework) — closing the loop between "it generated tests" and "here they
are." Project-scoped, VIEW-gated, read-only (the viewer never mutates a case).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.models.test_case import TestCase
from app.repositories.node_repository import NodeRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository
from app.services.case_review_service import CaseReviewError, CaseReviewService
from app.services.csv_test_import_service import CsvTestImportService

from .authz import authorize_project
from .deps import CurrentUser, get_session
from .schemas import (
    CaseReviewResponse,
    CsvImportResponse,
    CsvImportRowError,
    TestCaseListResponse,
    TestCaseSummary,
)

router = APIRouter(prefix="/api/v1", tags=["tests"])

# A CSV of scenarios is small text; cap it like the document upload so a pathological
# file can't wedge the request (the row cap in csv_import.py is the second bound).
_MAX_CSV_BYTES = 1_000_000


def _target_label(case: TestCase, names: dict[uuid.UUID, str]) -> str:
    """The human-readable target a case tests.

    Prefer the resolved Brain node name; else the target the generator recorded in
    ``case_key`` ("METHOD path::type::…" → the part before the first "::"); else a
    dash. Generated cases carry their target in ``case_key`` (``target_node`` is
    frequently unset), so the key fallback is what makes the viewer readable at all.
    """
    if case.target_node is not None:
        name = names.get(case.target_node)
        if name:
            return name
    if case.case_key:
        return case.case_key.split("::", 1)[0]
    return "—"


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
        items.append(
            TestCaseSummary(
                id=case.id,
                target=_target_label(case, names),
                type=case.type.value,
                layer=case.layer.value,
                oracle_source=case.oracle_source.value,
                framework=script.framework.value if script else "—",
                code=script.code if script else "",
                created_at=case.created_at,
                origin=case.origin.value,
                proposal_status=(
                    case.proposal_status.value if case.proposal_status else None
                ),
            )
        )

    total = await case_repo.count_current(project_id)
    return TestCaseListResponse(items=items, total=total)


@router.post("/projects/{project_id}/tests/import", response_model=CsvImportResponse)
async def import_tests_csv(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File()],
) -> CsvImportResponse:
    """Import QA-authored test scenarios from a CSV (multipart), MANAGE_PROJECT.

    Each row becomes a deterministic, runnable test the QA fully specified — no AI, so
    the import is reproducible and never invents an assertion. Idempotent: re-uploading
    a corrected CSV updates each scenario in place. A partial file succeeds — valid
    rows are persisted, invalid rows are returned for the QA to fix (never dropped).
    """
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )

    raw = await file.read()
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV too large")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 text") from None
    if not content.strip():
        raise HTTPException(status_code=400, detail="CSV is empty")

    result = await CsvTestImportService(session).import_csv(project_id, content)
    return CsvImportResponse(
        total=result.total,
        created=result.created,
        updated=result.updated,
        errors=[
            CsvImportRowError(row=error.row, message=error.message)
            for error in result.errors
        ],
    )


@router.post(
    "/projects/{project_id}/tests/{case_id}/accept",
    response_model=CaseReviewResponse,
)
async def accept_test(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CaseReviewResponse:
    """Accept a pending authored proposal — it stays current and runs (MANAGE)."""
    return await _review(project_id, case_id, current_user, session, accept=True)


@router.post(
    "/projects/{project_id}/tests/{case_id}/discard",
    response_model=CaseReviewResponse,
)
async def discard_test(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CaseReviewResponse:
    """Discard a pending authored proposal — it drops from the viewer and never runs."""
    return await _review(project_id, case_id, current_user, session, accept=False)


async def _review(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession,
    *,
    accept: bool,
) -> CaseReviewResponse:
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    service = CaseReviewService(session)
    try:
        if accept:
            case = await service.accept(
                project_id, case_id, reviewed_by=current_user.email
            )
        else:
            case = await service.discard(
                project_id, case_id, reviewed_by=current_user.email
            )
    except CaseReviewError as error:
        # Not found OR not a pending proposal → 404 (existence not leaked; a plain
        # generated/already-resolved case is not a reviewable resource).
        raise HTTPException(status_code=404, detail=str(error)) from None
    return CaseReviewResponse(
        id=case.id,
        proposal_status=case.proposal_status.value if case.proposal_status else "",
        is_current=case.is_current,
    )
