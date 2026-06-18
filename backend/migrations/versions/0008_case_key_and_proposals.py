"""case_key for re-gen matching + proposal versions (clobber-protection)

Revision ID: 0008_case_key_and_proposals
Revises: 0007_case_lineage
Create Date: 2026-06-18

Forward-only and additive (Standards §14). Adds the substrate for the
re-generation merge engine (T3.2):

- ``test_cases.case_key`` — the deterministic logical-case identity used to match
  a fresh generation against an existing lineage (indexed by ``project_id``).
- ``case_origin`` gains ``proposed`` — a re-gen against a human-edited case is
  recorded as a non-current proposal, never overwriting the human version.
- ``proposal_status`` enum + nullable column — ``pending`` when a proposal is
  created; ``accepted``/``rejected`` written later by resolution (T3.3).

``case_key`` is nullable: rows that predate keying keep NULL and simply won't be
matched by re-generation (acceptable — the same forward-only deferral as
node-deletion handling in T2.6). No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_case_key_and_proposals"
down_revision: str | None = "0007_case_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

proposal_status = postgresql.ENUM(
    "pending", "accepted", "rejected", name="proposal_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()

    # Extend the existing case_origin enum (created in 0007). Permitted inside a
    # transaction on Postgres 12+; the value is not used within this migration.
    op.execute("ALTER TYPE case_origin ADD VALUE IF NOT EXISTS 'proposed'")

    proposal_status.create(bind, checkfirst=True)

    op.add_column(
        "test_cases", sa.Column("case_key", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "test_cases", sa.Column("proposal_status", proposal_status, nullable=True)
    )
    op.create_index(
        "ix_test_cases_project_id_case_key",
        "test_cases",
        ["project_id", "case_key"],
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    # Note: an added enum value cannot be removed in Postgres without recreating
    # the type; 'proposed' is left in place (harmless, forward-only).
    op.drop_index("ix_test_cases_project_id_case_key", table_name="test_cases")
    op.drop_column("test_cases", "proposal_status")
    op.drop_column("test_cases", "case_key")
    proposal_status.drop(op.get_bind(), checkfirst=True)
