"""spec-vs-code reconciliation signals: spec_divergences (B9, ADR-0039)

Revision ID: 0022_spec_divergences
Revises: 0021_documents
Create Date: 2026-06-22

Forward-only and additive (Standards §14): a per-project table of concrete,
high-confidence spec-vs-code divergences flagged on document ingest. No new enum
(kind/confidence/status are validated strings). No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_spec_divergences"
down_revision: str | None = "0021_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


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
        "spec_divergences",
        *_audit_columns(),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("document_id", _UUID, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("spec_reference", sa.String(length=512), nullable=False),
        sa.Column("code_observation", sa.String(length=512), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column(
            "confidence",
            sa.String(length=16),
            server_default=sa.text("'high'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_spec_divergences"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_spec_divergences_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["project_documents.id"],
            name="fk_spec_divergences_document_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_spec_divergences_project_id", "spec_divergences", ["project_id"]
    )
    op.create_index(
        "ix_spec_divergences_document_id", "spec_divergences", ["document_id"]
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("ix_spec_divergences_document_id", table_name="spec_divergences")
    op.drop_index("ix_spec_divergences_project_id", table_name="spec_divergences")
    op.drop_table("spec_divergences")
