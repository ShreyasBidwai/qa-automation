"""business documents: project_documents + document_chunks (B9)

Revision ID: 0021_documents
Revises: 0020_durable_jobs
Create Date: 2026-06-22

Forward-only and additive (Standards §14): a per-project document store
(``project_documents``) and its embedded chunks (``document_chunks``) — chunk
vectors live in the same pgvector space as the code Brain (model_nodes), HNSW-indexed
for cosine ANN. No new enum (doc_kind is a validated string). No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_documents"
down_revision: str | None = "0020_durable_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_EMBEDDING_DIM = 384


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "project_documents",
        *_audit_columns(),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("doc_kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_project_documents"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_documents_project_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_project_documents_project_id", "project_documents", ["project_id"]
    )

    op.create_table(
        "document_chunks",
        *_audit_columns(),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("document_id", _UUID, nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_sha", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_document_chunks_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["project_documents.id"],
            name="fk_document_chunks_document_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "ordinal", name="uq_document_chunks_document_ordinal"
        ),
    )
    op.create_index(
        "ix_document_chunks_project_id", "document_chunks", ["project_id"]
    )
    op.create_index(
        "ix_document_chunks_document_id", "document_chunks", ["document_id"]
    )
    # Cosine ANN over chunk vectors (mirrors model_nodes' HNSW, migration 0005).
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_project_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_project_documents_project_id", table_name="project_documents")
    op.drop_table("project_documents")
