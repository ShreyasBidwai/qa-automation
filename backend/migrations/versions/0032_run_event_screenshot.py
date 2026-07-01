"""per-step screenshot ref on run_events for the live browser view (ADR-0050/0051)

Revision ID: 0032_run_event_screenshot
Revises: 0031_target_credentials
Create Date: 2026-06-30

Forward-only and additive (Standards §14): a nullable opaque screenshot ref on a
progress event, so a crawled page's frame (and a failing test's capture) can be
served live via the authorized ``GET /runs/{run_id}/events/screenshot?seq=N``. No
foreign key, no backfill, no destructive ops — old events simply have NULL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032_run_event_screenshot"
down_revision: str | None = "0031_target_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_events",
        sa.Column("screenshot_ref", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_column("run_events", "screenshot_ref")
