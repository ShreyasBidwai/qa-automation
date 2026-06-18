"""authored case_origin value for Mode A human-authored cases — T3 Mode A

Revision ID: 0010_authored_case_origin
Revises: 0009_proposal_resolution
Create Date: 2026-06-18

Forward-only and additive (Standards §14). Extends the ``case_origin`` enum with
``authored`` — a case a human wrote from scratch (Mode A), distinct from
``generated`` (AI), ``edited`` (a human edit of a prior version), and
``proposed`` (a re-generation awaiting resolution). No table or column changes;
existing rows are unaffected.

As in 0008, the value is added with ``ALTER TYPE ... ADD VALUE`` and is NOT used
within this migration (Postgres forbids using a freshly added enum value in the
same transaction that added it).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_authored_case_origin"
down_revision: str | None = "0009_proposal_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE case_origin ADD VALUE IF NOT EXISTS 'authored'")


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    # An added enum value cannot be removed in Postgres without recreating the
    # type; 'authored' is left in place (harmless, forward-only) — matching 0008.
    pass
