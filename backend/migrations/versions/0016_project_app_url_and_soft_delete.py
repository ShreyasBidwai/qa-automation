"""project app_url column + soft-delete (Sprint B1)

Revision ID: 0016_project_app_url
Revises: 0015_finding_triage
Create Date: 2026-06-21

Forward-only and additive (Standards §14): two nullable columns on ``projects`` —
``app_url`` (the crawl/E2E target base URL, promoted to a first-class column from
the ``settings`` jsonb and backfilled) and ``deleted_at`` (soft-delete marker,
ADR-0029). Does NOT alter any other table. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_project_app_url"
down_revision: str | None = "0015_finding_triage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects", sa.Column("app_url", sa.String(length=2048), nullable=True)
    )
    op.add_column(
        "projects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill app_url from the existing settings jsonb so pre-B1 projects keep it.
    op.execute(
        "UPDATE projects SET app_url = settings->>'app_url' "
        "WHERE settings ? 'app_url' AND settings->>'app_url' IS NOT NULL"
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_column("projects", "deleted_at")
    op.drop_column("projects", "app_url")
