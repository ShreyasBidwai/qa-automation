"""brain: model_nodes + model_edges (TRD §3, §7)

Revision ID: 0004_brain_nodes_and_edges
Revises: 0003_coverage
Create Date: 2026-06-17

Forward-only and additive (Standards §14): two enum types + two project-scoped
tables and their FK/unique/hot-path indexes. No embedding column yet — that
lands in T2.3 once the embedding dimension is chosen. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_brain_nodes_and_edges"
down_revision: str | None = "0003_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

node_kind = postgresql.ENUM(
    "endpoint", "page", "model", "table", "role", name="node_kind", create_type=False
)
edge_kind = postgresql.ENUM(
    "calls",
    "implements",
    "reads",
    "writes",
    "covers",
    "observed_in",
    "derived_from",
    name="edge_kind",
    create_type=False,
)

_ENUMS = (node_kind, edge_kind)
_UUID = postgresql.UUID(as_uuid=True)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("project_id", _UUID, nullable=False),
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
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "model_nodes",
        *_audit_columns(),
        sa.Column("kind", node_kind, nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_sha", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_model_nodes"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_model_nodes_project_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id", "kind", "name", name="uq_model_nodes_project_kind_name"
        ),
    )
    op.create_index("ix_model_nodes_project_id", "model_nodes", ["project_id"])
    op.create_index(
        "ix_model_nodes_project_id_source_sha",
        "model_nodes",
        ["project_id", "source_sha"],
    )

    op.create_table(
        "model_edges",
        *_audit_columns(),
        sa.Column("src_node_id", _UUID, nullable=False),
        sa.Column("dst_node_id", _UUID, nullable=False),
        sa.Column("kind", edge_kind, nullable=False),
        sa.Column(
            "confidence", sa.Float(), server_default=sa.text("1.0"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_edges"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_model_edges_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["src_node_id"],
            ["model_nodes.id"],
            name="fk_model_edges_src_node_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dst_node_id"],
            ["model_nodes.id"],
            name="fk_model_edges_dst_node_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id",
            "src_node_id",
            "dst_node_id",
            "kind",
            name="uq_model_edges_project_src_dst_kind",
        ),
    )
    op.create_index("ix_model_edges_project_id", "model_edges", ["project_id"])
    op.create_index("ix_model_edges_src_node_id", "model_edges", ["src_node_id"])
    op.create_index("ix_model_edges_dst_node_id", "model_edges", ["dst_node_id"])


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_table("model_edges")
    op.drop_table("model_nodes")
    bind = op.get_bind()
    for enum_type in reversed(_ENUMS):
        enum_type.drop(bind, checkfirst=True)
