"""Real-fastembed document round-trip (B9) — embed lane only.

Marked ``embed``: runs ONLY in `make test-embeddings`, where fastembed is installed.
Proves a document chunks + embeds with the REAL local provider and that pgvector
cosine search retrieves the most relevant chunk — closing stub-vs-real drift for the
documents path.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.service import DocumentService
from app.embeddings.fastembed_provider import LocalEmbeddingProvider
from app.models.model_node import EMBEDDING_DIM
from app.repositories.document_chunk_repository import DocumentChunkRepository
from tests.factories import make_project

pytestmark = pytest.mark.embed


def _provider() -> LocalEmbeddingProvider:
    return LocalEmbeddingProvider(
        model="BAAI/bge-small-en-v1.5", dimension=EMBEDDING_DIM
    )


async def test_real_document_embed_and_retrieve(db_session: AsyncSession) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    # Topical paragraphs, each long enough to chunk separately (the 1000-char
    # budget) so retrieval is a meaningful ranking, not a single chunk.
    email = "The email address must be unique for every account. " * 12
    shipping = "The shipping address is required for physical goods. " * 12
    refunds = "Refunds are processed within fourteen days of the request. " * 12
    provider = _provider()
    service = DocumentService(db_session, embedding_provider=provider)
    document = await service.add_document(
        project_id=project.id,
        title="Checkout requirements",
        doc_kind="requirements",
        content=f"{email}\n\n{shipping}\n\n{refunds}",
    )

    chunks = DocumentChunkRepository(db_session)
    stored = await chunks.list_for_document(project.id, document.id)
    assert len(stored) >= 2  # chunked, not one blob
    assert all(
        c.embedding is not None and len(c.embedding) == EMBEDDING_DIM for c in stored
    )

    # A semantic query about email uniqueness retrieves the email chunk first.
    query_vec = provider.embed(["how is the email handled for accounts?"])[0]
    hits = await chunks.search_by_vector(project.id, query_vec, k=3)
    assert hits and "email" in hits[0].text.lower()
