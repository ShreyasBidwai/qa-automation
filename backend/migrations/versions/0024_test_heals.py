"""flagged, confirmable addressing heals: test_heals (B8, ADR-0040)

Revision ID: 0024_test_heals
Revises: 0023_results_message
Create Date: 2026-06-22

Forward-only and additive (Standards §14): a per-project table of proposed
addressing heals. ``kind``/``failure_class``/``confidence``/``status`` are
validated strings (no new enum). A unique ``(test_case_id, before_addr,
after_addr)`` makes re-proposing the same heal idempotent. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_test_heals"
down_revision: str | None = "0023_results_message"
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
        "test_heals",
        *_audit_columns(),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("run_id", _UUID, nullable=True),
        sa.Column("test_case_id", _UUID, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("failure_class", sa.String(length=16), nullable=False),
        sa.Column("before_addr", sa.String(length=1024), nullable=False),
        sa.Column("after_addr", sa.String(length=1024), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "confidence",
            sa.String(length=16),
            server_default=sa.text("'high'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'proposed'"),
            nullable=False,
        ),
        sa.Column("healed_code", sa.Text(), nullable=False),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_test_heals"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_test_heals_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name="fk_test_heals_run_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name="fk_test_heals_test_case_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "test_case_id",
            "before_addr",
            "after_addr",
            name="uq_test_heals_dedup",
        ),
    )
    op.create_index("ix_test_heals_project_id", "test_heals", ["project_id"])
    op.create_index("ix_test_heals_test_case_id", "test_heals", ["test_case_id"])
    op.create_index(
        "ix_test_heals_project_id_run_id", "test_heals", ["project_id", "run_id"]
    )
    op.create_index(
        "ix_test_heals_project_id_status", "test_heals", ["project_id", "status"]
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("ix_test_heals_project_id_status", table_name="test_heals")
    op.drop_index("ix_test_heals_project_id_run_id", table_name="test_heals")
    op.drop_index("ix_test_heals_test_case_id", table_name="test_heals")
    op.drop_index("ix_test_heals_project_id", table_name="test_heals")
    op.drop_table("test_heals")
