"""persist runner failure detail on results: results.message (B8, ADR-0040)

Revision ID: 0023_results_message
Revises: 0022_spec_divergences
Create Date: 2026-06-22

Forward-only and additive (Standards §14): a nullable ``message`` column carrying
the runner's failure text, so the self-healing classifier can split location vs
assertion failures after a run. Existing rows keep NULL; no destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023_results_message"
down_revision: str | None = "0022_spec_divergences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("results", sa.Column("message", sa.Text(), nullable=True))


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_column("results", "message")
