"""findings: assembled bug objects the report is built from (T7.1)

Revision ID: 0013_findings
Revises: 0012_auth_challenge_log
Create Date: 2026-06-19

Forward-only and additive (Standards §14): a ``finding_layer`` enum + a new
project-scoped ``findings`` table referencing ``runs`` and ``results``. Does NOT
alter ``results`` (or any existing table). The ``oracle_source`` column reuses the
enum type created in 0004. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_findings"
down_revision: str | None = "0012_auth_challenge_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

finding_layer = postgresql.ENUM("ui", "api", "db", name="finding_layer", create_type=False)
# Existing type (0004) — referenced, never recreated.
oracle_source = postgresql.ENUM(
    "rule-derived",
    "characterization",
    "spec-grounded",
    name="oracle_source",
    create_type=False,
)
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    finding_layer.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "findings",
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
        sa.Column("run_id", _UUID, nullable=False),
        sa.Column("result_id", _UUID, nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("layer", finding_layer, nullable=False),
        sa.Column("oracle_source", oracle_source, nullable=False),
        sa.Column(
            "expected",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("evidence_ref", sa.String(length=512), nullable=True),
        sa.Column(
            "location",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "severity", sa.String(length=32), server_default=sa.text("'unset'"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_findings"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_findings_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_findings_run_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["result_id"], ["results.id"], name="fk_findings_result_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_findings_project_id", "findings", ["project_id"])
    op.create_index("ix_findings_run_id", "findings", ["run_id"])
    op.create_index("ix_findings_result_id", "findings", ["result_id"])


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_table("findings")
    finding_layer.drop(op.get_bind(), checkfirst=True)
