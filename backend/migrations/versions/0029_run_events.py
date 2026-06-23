"""ordered run-progress events for the live run view: run_events (ADR-0050)

Revision ID: 0029_run_events
Revises: 0028_ai_usage
Create Date: 2026-06-23

Forward-only and additive (Standards §14): a standalone log of run-progress events,
keyed by ``run_id`` (the API run id / RUN job id) with NO foreign key — like
``incidents`` / ``ai_usage`` it records what happened during a run and outlives the
entities it references. ``phase``/``status`` are validated strings (no enum);
``detail`` is optional JSONB. The unique ``(run_id, seq)`` index enforces deterministic
ordering. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029_run_events"
down_revision: str | None = "0028_ai_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "run_events",
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
        sa.Column("run_id", _UUID, nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("step", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_run_events"),
    )
    op.create_index(
        "uq_run_events_run_id_seq", "run_events", ["run_id", "seq"], unique=True
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("uq_run_events_run_id_seq", table_name="run_events")
    op.drop_table("run_events")
