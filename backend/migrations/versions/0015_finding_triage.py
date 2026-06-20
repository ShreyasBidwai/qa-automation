"""finding triage: disposition keyed by the logical issue (ADR-0027)

Revision ID: 0015_finding_triage
Revises: 0014_finding_grouping
Create Date: 2026-06-20

Forward-only and additive (Standards §14): a ``triage_status`` enum + a new
project-scoped ``finding_triage`` table keyed ``(project_id, root_cause_key)`` so
a triage disposition follows the logical issue across runs. Does NOT alter
``findings`` or any existing table. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_finding_triage"
down_revision: str | None = "0014_finding_grouping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

triage_status = postgresql.ENUM(
    "open",
    "acknowledged",
    "resolved",
    "wont_fix",
    "false_positive",
    name="triage_status",
    create_type=False,
)
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    triage_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "finding_triage",
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
        sa.Column("root_cause_key", sa.String(length=512), nullable=False),
        sa.Column("status", triage_status, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_finding_triage"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_finding_triage_project_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id",
            "root_cause_key",
            name="uq_finding_triage_project_id_root_cause_key",
        ),
    )
    op.create_index("ix_finding_triage_project_id", "finding_triage", ["project_id"])


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_table("finding_triage")
    triage_status.drop(op.get_bind(), checkfirst=True)
