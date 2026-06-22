"""DocumentService — ingest a business document into the Brain (B9).

Deterministic chunk → batched embed (one provider call, no N+1) → persist. The
embedding provider is injected (the local fastembed in prod/embed-lane, the
deterministic stub in the fast lane), so this never makes a network/API call.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.errors import EmbeddingDimMismatch
from app.embeddings.types import EmbeddingProvider
from app.models.document_chunk import DocumentChunk
from app.models.model_node import EMBEDDING_DIM
from app.models.project_document import ProjectDocument
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.project_document_repository import ProjectDocumentRepository

from .chunk import chunk_text


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentService:
    def __init__(
        self, session: AsyncSession, *, embedding_provider: EmbeddingProvider
    ) -> None:
        self._session = session
        self._docs = ProjectDocumentRepository(session)
        self._chunks = DocumentChunkRepository(session)
        self._embedding = embedding_provider

    async def add_document(
        self,
        *,
        project_id: uuid.UUID,
        title: str,
        doc_kind: str,
        content: str,
    ) -> ProjectDocument:
        """Persist a document and its chunked, embedded slices (one embed call)."""
        document = await self._docs.add(
            ProjectDocument(
                project_id=project_id,
                title=title,
                doc_kind=doc_kind,
                content=content,
                content_sha=_sha(content),
            )
        )
        texts = chunk_text(content)
        if texts:
            vectors = self._embedding.embed(texts)
            chunks: list[DocumentChunk] = []
            for ordinal, (text, vector) in enumerate(zip(texts, vectors, strict=True)):
                if len(vector) != EMBEDDING_DIM:
                    raise EmbeddingDimMismatch(
                        f"provider returned dim {len(vector)}, "
                        f"column expects {EMBEDDING_DIM}"
                    )
                chunks.append(
                    DocumentChunk(
                        project_id=project_id,
                        document_id=document.id,
                        ordinal=ordinal,
                        text=text,
                        content_sha=_sha(text),
                        embedding=vector,
                    )
                )
            await self._chunks.add_many(chunks)
        return document
