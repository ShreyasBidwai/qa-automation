"""brain node embeddings: model_nodes.embedding vector(384) + HNSW (TRD §7)

Revision ID: 0005_node_embeddings
Revises: 0004_brain_nodes_and_edges
Create Date: 2026-06-18

Forward-only and additive (Standards §14): add a nullable pgvector embedding
column and an HNSW index for cosine ANN. The `vector` extension is already
enabled (migration 0001). No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0005_node_embeddings"
down_revision: str | None = "0004_brain_nodes_and_edges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMBEDDING_DIM = 384


def upgrade() -> None:
    op.add_column(
        "model_nodes",
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=True),
    )
    # HNSW index for cosine distance (<=>) ANN search (pgvector 0.8).
    op.create_index(
        "ix_model_nodes_embedding_hnsw",
        "model_nodes",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("ix_model_nodes_embedding_hnsw", table_name="model_nodes")
    op.drop_column("model_nodes", "embedding")
