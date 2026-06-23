"""Business-document routes (B9) — project-scoped, RBAC-gated.

Attach / list / remove documents on a project, and list the spec-vs-code
divergences reconciliation flagged on ingest (ADR-0039). Adding/removing is a
project mutation (MANAGE_PROJECT — member+); listing needs VIEW. The ingest path
chunks + embeds into the Brain and runs the static reconciliation pass.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, get_args

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.documents.reconcile import reconcile_document
from app.documents.service import DocumentService
from app.embeddings.errors import EmbeddingError
from app.embeddings.types import EmbeddingProvider
from app.models.project_document import ProjectDocument
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.project_document_repository import ProjectDocumentRepository
from app.repositories.spec_divergence_repository import SpecDivergenceRepository

from .authz import authorize_project
from .deps import CurrentUser, get_embedding_provider, get_session
from .schemas import (
    DocumentCreate,
    DocumentKind,
    DocumentListResponse,
    DocumentResponse,
    SpecDivergenceListResponse,
    SpecDivergenceResponse,
)

logger = logging.getLogger("app.api.documents")
router = APIRouter(prefix="/api/v1", tags=["documents"])

# Accepted document kinds (kept in sync with the DocumentKind Literal).
_DOC_KINDS: frozenset[str] = frozenset(get_args(DocumentKind))
_MAX_UPLOAD_BYTES = 1_000_000  # mirrors the DocumentCreate.content cap (B9)


def _document_response(document: ProjectDocument, chunk_count: int) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        title=document.title,
        doc_kind=document.doc_kind,
        chunk_count=chunk_count,
        created_at=document.created_at,
    )


@router.post(
    "/projects/{project_id}/documents",
    status_code=201,
    response_model=DocumentResponse,
)
async def add_document(
    project_id: uuid.UUID,
    body: DocumentCreate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> DocumentResponse:
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    service = DocumentService(session, embedding_provider=embedding)
    document = await service.add_document(
        project_id=project_id,
        title=body.title,
        doc_kind=body.doc_kind,
        content=body.content,
    )
    # Static spec-vs-code reconciliation on ingest (ADR-0039), confidence-gated.
    await reconcile_document(session, project_id=project_id, document=document)
    counts = await DocumentChunkRepository(session).counts_by_document(project_id)
    return _document_response(document, counts.get(document.id, 0))


@router.post(
    "/projects/{project_id}/documents/upload",
    status_code=201,
    response_model=DocumentResponse,
)
async def upload_document(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    doc_kind: Annotated[str, Form()] = "requirements",
) -> DocumentResponse:
    """Attach a document by FILE UPLOAD (multipart), reusing the B9 chunk+embed
    pipeline (ADR-0052). MANAGE_PROJECT, like the JSON attach. The UTF-8 text body
    is chunked + embedded into the Brain; an embedding failure rolls the request
    back cleanly (502) — the project is never left corrupted (best-effort)."""
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    if doc_kind not in _DOC_KINDS:
        raise HTTPException(status_code=422, detail=f"unknown doc_kind {doc_kind!r}")

    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="document too large")
    try:
        content = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400, detail="document must be UTF-8 text"
        ) from None
    if not content:
        raise HTTPException(status_code=400, detail="document is empty")

    resolved_title = (title or file.filename or "document").strip()[:512] or "document"
    service = DocumentService(session, embedding_provider=embedding)
    try:
        document = await service.add_document(
            project_id=project_id,
            title=resolved_title,
            doc_kind=doc_kind,
            content=content,
        )
        await reconcile_document(session, project_id=project_id, document=document)
    except EmbeddingError:
        # Best-effort embed (ADR-0052): get_session rolls the request back, so the
        # project is untouched; surface a clean 502 rather than a raw 500.
        logger.warning(
            "documents.upload_embed_failed", extra={"project_id": str(project_id)}
        )
        raise HTTPException(
            status_code=502, detail="document embedding failed"
        ) from None
    counts = await DocumentChunkRepository(session).counts_by_document(project_id)
    return _document_response(document, counts.get(document.id, 0))


@router.get("/projects/{project_id}/documents", response_model=DocumentListResponse)
async def list_documents(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentListResponse:
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    documents = await ProjectDocumentRepository(session).list(project_id)
    counts = await DocumentChunkRepository(session).counts_by_document(project_id)
    items = [_document_response(doc, counts.get(doc.id, 0)) for doc in documents]
    return DocumentListResponse(items=items, total=len(items))


@router.delete("/projects/{project_id}/documents/{document_id}", status_code=204)
async def remove_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    if not await ProjectDocumentRepository(session).delete(project_id, document_id):
        raise HTTPException(status_code=404, detail="document not found")
    return Response(status_code=204)  # chunks + divergences cascade


@router.get(
    "/projects/{project_id}/spec-divergences",
    response_model=SpecDivergenceListResponse,
)
async def list_spec_divergences(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SpecDivergenceListResponse:
    """Concrete, high-confidence spec-vs-code divergences (ADR-0039)."""
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    rows = await SpecDivergenceRepository(session).list(project_id)
    items = [
        SpecDivergenceResponse(
            id=row.id,
            document_id=row.document_id,
            kind=row.kind,
            spec_reference=row.spec_reference,
            code_observation=row.code_observation,
            excerpt=row.excerpt,
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return SpecDivergenceListResponse(items=items, total=len(items))
