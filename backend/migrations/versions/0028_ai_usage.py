"""per-invocation AI usage + actual billed cost: ai_usage (ADR-0049)

Revision ID: 0028_ai_usage
Revises: 0027_run_numbers
Create Date: 2026-06-23

Forward-only and additive (Standards §14): a standalone log of what each model
invocation cost, attributed to a run + phase. Like ``incidents`` it is an
observability log keyed by ``project_id``/``run_id`` with NO foreign key (it records
what an invocation cost and outlives the entities it references). ``phase`` is a
validated string (no enum); token/cost columns are nullable for best-effort capture
(NULL when the CLI envelope could not be parsed). No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028_ai_usage"
down_revision: str | None = "0027_run_numbers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_COST = sa.Numeric(14, 8)


def upgrade() -> None:
    op.create_table(
        "ai_usage",
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
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("run_id", _UUID, nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=True),
        sa.Column("total_cost_usd", _COST, nullable=True),
        sa.Column("model_cost_usd", _COST, nullable=True),
        sa.Column("usage_available", sa.Boolean(), nullable=False),
        sa.Column("is_error", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ai_usage"),
    )
    op.create_index(
        "ix_ai_usage_project_id_run_id", "ai_usage", ["project_id", "run_id"]
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("ix_ai_usage_project_id_run_id", table_name="ai_usage")
    op.drop_table("ai_usage")
