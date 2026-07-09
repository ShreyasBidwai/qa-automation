"""sessions.impersonated_by — auditable staff impersonation (ADR-0071)

Revision ID: 0041_session_impersonated_by
Revises: 0040_testcase_gen_version
Create Date: 2026-07-08

Forward-only and additive (Standards §14). A nullable FK to the staff actor when a
session was minted by impersonation; NULL for a normal login. SET NULL on actor delete
so the session (and the customer's access) survives a deleted staff account.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0041_session_impersonated_by"
down_revision: str | None = "0040_testcase_gen_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("impersonated_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sessions_impersonated_by",
        "sessions",
        "users",
        ["impersonated_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_impersonated_by", "sessions", type_="foreignkey")
    op.drop_column("sessions", "impersonated_by")
