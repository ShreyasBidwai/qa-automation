"""organizations.suspended_at — staff suspension of a tenant (ADR-0068)

Revision ID: 0037_org_suspended_at
Revises: 0036_staff_audit_log
Create Date: 2026-07-08

Forward-only and additive (Standards §14). A nullable timestamp: NULL = active, set =
suspended by platform staff. Reversible; removes nothing (distinct from org deletion).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037_org_suspended_at"
down_revision: str | None = "0036_staff_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "suspended_at")
