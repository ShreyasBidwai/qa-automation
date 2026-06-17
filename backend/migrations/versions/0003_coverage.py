"""coverage table (TRD §3)

Revision ID: 0003_coverage
Revises: 0002_core_test_data_model
Create Date: 2026-06-17

Forward-only and additive (Standards §14): one enum type + one project-scoped
table recording what a run closed per dimension and its gaps. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_coverage"
down_revision: str | None = "0002_core_test_data_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

coverage_dimension = postgresql.ENUM(
    "endpoint",
    "page",
    "journey",
    "role-matrix",
    name="coverage_dimension",
    create_type=False,
)

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    bind = op.get_bind()
    coverage_dimension.create(bind, checkfirst=True)

    op.create_table(
        "coverage",
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
        sa.Column("dimension", coverage_dimension, nullable=False),
        sa.Column(
            "covered",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "gaps",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_coverage"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_coverage_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_coverage_run_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_coverage_project_id", "coverage", ["project_id"])
    op.create_index("ix_coverage_run_id", "coverage", ["run_id"])


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_table("coverage")
    coverage_dimension.drop(op.get_bind(), checkfirst=True)
