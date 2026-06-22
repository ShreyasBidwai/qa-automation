"""Business documents — chunk, embed, retrieve, endpoints + RBAC (B9).

Hermetic: the deterministic StubEmbeddingProvider (no model download). The real
fastembed embed→retrieve round-trip lives in test_documents_embed.py (embed lane).
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.chunk import chunk_text
from app.documents.service import DocumentService
from app.embeddings.stub import StubEmbeddingProvider
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.organization_repository import OrganizationRepository
from tests.factories import make_project


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _email() -> str:
    return f"doc-{uuid.uuid4().hex[:12]}@example.test"


async def _signup(client: AsyncClient) -> tuple[str, uuid.UUID]:
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": _email(), "password": "passw0rd1"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


async def _create_project(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Docs", "repo_url": "https://git/docs.git"},
        headers=_h(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- chunking (pure) ---------------------------------------------------------


def test_chunk_text_packs_paragraphs_within_budget() -> None:
    content = "Para one.\n\nPara two is here.\n\nThird paragraph."
    chunks = chunk_text(content, max_chars=1000)
    assert chunks == ["Para one.\nPara two is here.\nThird paragraph."]


def test_chunk_text_splits_over_budget() -> None:
    content = "a" * 50 + "\n\n" + "b" * 50
    chunks = chunk_text(content, max_chars=60)
    assert len(chunks) == 2 and all(len(c) <= 60 for c in chunks)


def test_chunk_text_hard_splits_a_long_paragraph() -> None:
    chunks = chunk_text("word " * 100, max_chars=40)
    assert len(chunks) > 1 and all(len(c) <= 40 for c in chunks)


def test_chunk_text_empty_is_empty() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


# --- service: ingest → embed → retrieve (stub) -------------------------------


async def test_add_document_chunks_embeds_and_is_retrievable(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    provider = StubEmbeddingProvider()
    service = DocumentService(db_session, embedding_provider=provider)
    content = (
        "Checkout requires a valid email.\n\n"
        "The order total must be positive.\n\n"
        "Discount codes are single-use."
    )
    document = await service.add_document(
        project_id=project.id,
        title="Checkout spec",
        doc_kind="requirements",
        content=content,
    )

    chunks = DocumentChunkRepository(db_session)
    stored = await chunks.list_for_document(project.id, document.id)
    assert stored and all(c.embedding is not None for c in stored)
    assert [c.ordinal for c in stored] == list(range(len(stored)))

    # The exact chunk text retrieves itself first (stub: identical text → distance 0).
    query_vec = provider.embed([stored[0].text])[0]
    hits = await chunks.search_by_vector(project.id, query_vec, k=3)
    assert hits and hits[0].id == stored[0].id


async def test_counts_by_document_is_batched(db_session: AsyncSession) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    service = DocumentService(db_session, embedding_provider=StubEmbeddingProvider())

    doc_a = await service.add_document(
        project_id=project.id, title="A", doc_kind="requirements", content="one para"
    )
    # Three ~800-char paragraphs exceed the 1000-char budget → three chunks.
    big = "\n\n".join(["x" * 800, "y" * 800, "z" * 800])
    doc_b = await service.add_document(
        project_id=project.id, title="B", doc_kind="api_contract", content=big
    )

    counts = await DocumentChunkRepository(db_session).counts_by_document(project.id)
    assert counts[doc_a.id] == 1 and counts[doc_b.id] == 3


# --- API + RBAC --------------------------------------------------------------


@pytest_asyncio.fixture
async def docs_client(
    app_client: tuple[AsyncClient, FastAPI],
) -> tuple[AsyncClient, FastAPI]:
    client, app = app_client
    app.state.embedding_provider = StubEmbeddingProvider()
    return client, app


async def test_document_endpoints_add_list_remove(
    docs_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = docs_client
    token, _ = await _signup(client)
    project_id = await _create_project(client, token)
    base = f"/api/v1/projects/{project_id}/documents"

    add = await client.post(
        base,
        json={"title": "Reqs", "doc_kind": "requirements", "content": "a\n\nb\n\nc"},
        headers=_h(token),
    )
    assert add.status_code == 201
    doc = add.json()
    assert doc["chunk_count"] >= 1 and doc["doc_kind"] == "requirements"

    listing = (await client.get(base, headers=_h(token))).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == doc["id"]

    removed = await client.delete(f"{base}/{doc['id']}", headers=_h(token))
    assert removed.status_code == 204
    assert (await client.get(base, headers=_h(token))).json()["total"] == 0
    assert (
        await client.delete(f"{base}/{doc['id']}", headers=_h(token))
    ).status_code == 404


async def test_add_document_requires_embedding_provider(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    app.state.embedding_provider = None  # not configured
    token, _ = await _signup(client)
    project_id = await _create_project(client, token)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/documents",
        json={"title": "x", "doc_kind": "requirements", "content": "y"},
        headers=_h(token),
    )
    assert resp.status_code == 503


async def test_document_rbac(docs_client: tuple[AsyncClient, FastAPI]) -> None:
    client, app = docs_client
    owner, owner_id = await _signup(client)
    viewer, viewer_id = await _signup(client)
    outsider, _ = await _signup(client)

    # A team org: owner + viewer; a project in it.
    async with app.state.sessionmaker() as session:
        repo = OrganizationRepository(session)
        org = await repo.add(Organization(name="Team", is_personal=False))
        org_id = org.id
        await repo.add_member(org_id, owner_id, OrgRole.OWNER)
        await repo.add_member(org_id, viewer_id, OrgRole.VIEWER)
        project = Project(
            name="P", slug=f"p-{uuid.uuid4().hex[:8]}", org_id=org_id, settings={}
        )
        session.add(project)
        await session.flush()
        project_id = project.id
        await session.commit()

    base = f"/api/v1/projects/{project_id}/documents"
    body = {"title": "x", "doc_kind": "requirements", "content": "y"}

    # owner (MANAGE_PROJECT) can add.
    assert (await client.post(base, json=body, headers=_h(owner))).status_code == 201
    # viewer can VIEW the list but NOT add (403).
    assert (await client.get(base, headers=_h(viewer))).status_code == 200
    assert (await client.post(base, json=body, headers=_h(viewer))).status_code == 403
    # a non-member is 404 (existence not leaked).
    assert (await client.get(base, headers=_h(outsider))).status_code == 404
    assert (await client.post(base, json=body, headers=_h(outsider))).status_code == 404
