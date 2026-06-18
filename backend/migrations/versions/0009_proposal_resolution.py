"""proposal resolution provenance (accept/reject) — T3.3

Revision ID: 0009_proposal_resolution
Revises: 0008_case_key_and_proposals
Create Date: 2026-06-18

Forward-only and additive (Standards §14). Adds the substrate for resolving a
re-generation proposal against a human-edited case (T3.3):

- ``test_cases.resolved_by`` — the human who accepted/rejected the proposal.
- ``test_cases.resolved_at`` — when the proposal was resolved.

Both are nullable and remain NULL on non-proposal rows and on still-pending
proposals; they are written only when a pending proposal becomes terminal
(``proposal_status`` accepted/rejected). No destructive ops, no backfill needed
(NULL is the correct value for every existing row — nothing has been resolved).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_proposal_resolution"
down_revision: str | None = "0008_case_key_and_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_cases", sa.Column("resolved_by", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "test_cases",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_column("test_cases", "resolved_at")
    op.drop_column("test_cases", "resolved_by")
