"""``document_chunks`` — embedded slices of a project document (B9).

Each chunk carries a pgvector embedding in the SAME space as the code-derived Brain
nodes (``model_nodes.embedding``), so generation retrieves documented contracts the
same way it resolves code. HNSW-indexed for cosine ANN (migration 0021).
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin
from .model_node import EMBEDDING_DIM


class DocumentChunk(Base, ProjectScopedMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "ordinal", name="uq_document_chunks_document_ordinal"
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # ADR-0010-style embed cache key: re-embed only when the chunk text changes.
    content_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
