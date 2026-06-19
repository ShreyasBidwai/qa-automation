"""finding grouping: root-cause key + finding_results join (T7.2)

Revision ID: 0014_finding_grouping
Revises: 0013_findings
Create Date: 2026-06-19

Forward-only and additive (Standards §14). Two things:
  1. New ``finding_results`` join table — one Finding now groups the many failing
     results that share a root cause (ADR-0021).
  2. Three additive columns on ``findings`` (root_cause_key, explains_count,
     confidence_mixed) + a unique index ``(run_id, root_cause_key)`` enforcing one
     finding per root cause per run.

Does NOT alter ``results`` (or any pre-T7.1 table). No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_finding_grouping"
down_revision: str | None = "0013_findings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # 1. Additive columns on the (T7.1) findings table.
    op.add_column(
        "findings",
        sa.Column(
            "root_cause_key",
            sa.String(length=512),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column(
        "findings",
        sa.Column(
            "explains_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "findings",
        sa.Column(
            "confidence_mixed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_findings_run_id_root_cause_key",
        "findings",
        ["run_id", "root_cause_key"],
        unique=True,
    )

    # 2. The membership join.
    op.create_table(
        "finding_results",
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
        sa.Column("finding_id", _UUID, nullable=False),
        sa.Column("result_id", _UUID, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_finding_results"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_finding_results_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name="fk_finding_results_finding_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["result_id"],
            ["results.id"],
            name="fk_finding_results_result_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "finding_id", "result_id", name="uq_finding_results_finding_id_result_id"
        ),
    )
    op.create_index("ix_finding_results_project_id", "finding_results", ["project_id"])
    op.create_index("ix_finding_results_finding_id", "finding_results", ["finding_id"])
    op.create_index("ix_finding_results_result_id", "finding_results", ["result_id"])


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_table("finding_results")
    op.drop_index("uq_findings_run_id_root_cause_key", table_name="findings")
    op.drop_column("findings", "confidence_mixed")
    op.drop_column("findings", "explains_count")
    op.drop_column("findings", "root_cause_key")
