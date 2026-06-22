"""Repository for ``document_chunks`` (B9) — project-scoped + cosine ANN search."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, func, select

from app.models.document_chunk import DocumentChunk
from app.models.model_node import EMBEDDING_DIM

from .base import ProjectScopedRepository


class DocumentChunkRepository(ProjectScopedRepository[DocumentChunk]):
    model = DocumentChunk

    async def add_many(self, chunks: Sequence[DocumentChunk]) -> list[DocumentChunk]:
        """Persist a document's chunks in one batched flush (no N+1)."""
        self.session.add_all(list(chunks))
        await self.session.flush()
        return list(chunks)

    async def counts_by_document(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Chunk count per document in ONE grouped query (no N+1 over the list)."""
        stmt = (
            select(DocumentChunk.document_id, func.count())
            .where(DocumentChunk.project_id == project_id)
            .group_by(DocumentChunk.document_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {document_id: count for document_id, count in rows}

    async def list_for_document(
        self, project_id: uuid.UUID, document_id: uuid.UUID
    ) -> list[DocumentChunk]:
        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.project_id == project_id,
                DocumentChunk.document_id == document_id,
            )
            .order_by(DocumentChunk.ordinal)
        )
        return list((await self.session.scalars(stmt)).all())

    async def search_by_vector(
        self, project_id: uuid.UUID, embedding: list[float], k: int = 5
    ) -> list[DocumentChunk]:
        """Top-k embedded chunks nearest the query vector (cosine), project-scoped.

        Uses pgvector ``<=>`` served by the HNSW index (migration 0021); chunks
        without an embedding are excluded.
        """
        query_vec = cast(list(embedding), Vector(EMBEDDING_DIM))
        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.project_id == project_id,
                DocumentChunk.embedding.is_not(None),
            )
            .order_by(DocumentChunk.embedding.op("<=>")(query_vec))
            .limit(k)
        )
        return list((await self.session.scalars(stmt)).all())
