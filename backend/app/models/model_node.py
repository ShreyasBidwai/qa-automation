"""``model_nodes`` — the system-model ("Brain") nodes (TRD §3, §7).

Endpoints/pages/models/tables/roles extracted from a target, versioned by
``source_sha``. Holds structure only — no business logic (Standards §5). Carries
a pgvector ``embedding`` for semantic NL→node resolution (T2.3); the Brain is
rebuildable from the codebase.
"""

from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import NodeKind

# Embedding dimension — the schema's source of truth. The configured embedding
# provider MUST produce vectors of this dimension (config embedding_dim).
EMBEDDING_DIM = 384


class ModelNode(Base, ProjectScopedMixin):
    __tablename__ = "model_nodes"
    __table_args__ = (
        # Idempotent re-ingestion is keyed on (project_id, kind, name); the
        # backing unique index also serves (project_id, kind) prefix lookups.
        UniqueConstraint(
            "project_id", "kind", "name", name="uq_model_nodes_project_kind_name"
        ),
        Index("ix_model_nodes_project_id_source_sha", "project_id", "source_sha"),
        Index("ix_model_nodes_project_id_content_sha", "project_id", "content_sha"),
    )

    kind: Mapped[NodeKind] = mapped_column(
        pg_enum(NodeKind, "node_kind"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Provenance / last-seen: the repo HEAD commit the node was last ingested
    # from (refreshed every re-ingest). Nullable: some nodes have no single file.
    source_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ADR-0010 cache key: a deterministic hash of the node's EXTRACTED content
    # (attributes + document). Re-ingest re-embeds only when this changes; an
    # identical content_sha is a cache hit (T2.6). Nullable until embedded.
    content_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Semantic embedding of the node's document (T2.3). Nullable: populated on
    # ingest when an embedding provider is configured. HNSW-indexed for cosine
    # ANN search (migration 0005).
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
