"""generation_signals — the self-improvement flywheel capture spine (ADR-0070)

Revision ID: 0039_generation_signals
Revises: 0038_plans
Create Date: 2026-07-08

Forward-only and additive (Standards §14). One append-only row per generated test
artifact, joining its input context + generation version to its execution/triage
outcome — the eval set + retrieval corpus + optimisation basis. Observability log
(no FK), like ai_usage/incidents.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0039_generation_signals"
down_revision: str | None = "0038_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "generation_signals",
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
        sa.Column("run_id", _UUID, nullable=True),
        sa.Column("test_case_id", _UUID, nullable=True),
        sa.Column("route_class", sa.String(length=32), nullable=True),
        sa.Column("framework", sa.String(length=32), nullable=True),
        sa.Column("target_kind", sa.String(length=32), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column(
            "repaired", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "healed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "flaky", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("triage", sa.String(length=16), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_generation_signals"),
    )
    op.create_index(
        "ix_generation_signals_project_id_run_id",
        "generation_signals",
        ["project_id", "run_id"],
    )
    op.create_index(
        "ix_generation_signals_prompt_version",
        "generation_signals",
        ["prompt_version"],
    )


def downgrade() -> None:
    op.drop_table("generation_signals")
