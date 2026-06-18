"""brain node content_sha cache key (ADR-0010, T2.6)

Revision ID: 0006_node_content_sha
Revises: 0005_node_embeddings
Create Date: 2026-06-18

Forward-only and additive (Standards §14): a nullable per-node ``content_sha``
(the ADR-0010 cache key — a hash of the node's extracted content, distinct from
``source_sha`` provenance) plus an index on (project_id, content_sha). No
destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_node_content_sha"
down_revision: str | None = "0005_node_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_nodes",
        sa.Column("content_sha", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_model_nodes_project_id_content_sha",
        "model_nodes",
        ["project_id", "content_sha"],
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("ix_model_nodes_project_id_content_sha", table_name="model_nodes")
    op.drop_column("model_nodes", "content_sha")
