"""per-project DB-state-testing tier: projects.db_state_tier (B10, ADR-0043)

Revision ID: 0025_db_state_tier
Revises: 0024_test_heals
Create Date: 2026-06-22

Forward-only and additive (Standards §14): one nullable-defaulted column carrying
the per-project DB-state-testing opt-in tier (off / read_only / full). A validated
string (no pg enum); existing rows default to ``off`` so the feature is opt-in and
nothing changes until an operator raises the tier. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_db_state_tier"
down_revision: str | None = "0024_test_heals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "db_state_tier",
            sa.String(length=16),
            server_default=sa.text("'off'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_column("projects", "db_state_tier")
