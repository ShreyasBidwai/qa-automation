"""failure screenshots: results.screenshot_ref + findings.screenshot_ref (ADR-0051)

Revision ID: 0030_finding_screenshot
Revises: 0029_run_events
Create Date: 2026-06-24

Forward-only and additive (Standards §14): a nullable opaque screenshot ref on
``results`` (captured at execution for a failing result) and on ``findings`` (copied
from the representative result by the assembler — the same path ``evidence_ref``
already takes). The bytes live behind the ``app.screenshots`` indirection, not in the
DB. No new enum, no destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_finding_screenshot"
down_revision: str | None = "0029_run_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "results", sa.Column("screenshot_ref", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "findings", sa.Column("screenshot_ref", sa.String(length=512), nullable=True)
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_column("findings", "screenshot_ref")
    op.drop_column("results", "screenshot_ref")
