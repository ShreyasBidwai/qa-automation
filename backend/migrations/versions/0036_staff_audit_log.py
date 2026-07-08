"""staff_audit_log — immutable record of cross-tenant staff actions (ADR-0068)

Revision ID: 0036_staff_audit_log
Revises: 0035_staff_roles
Create Date: 2026-07-08

Forward-only and additive (Standards §14). Every mutation in the operator/admin
console appends one row here: append-only, cross-tenant, with NO foreign key on the
target refs (the log outlives the entities it references). The actor FK is SET NULL
on user delete so the row survives a deleted staff account; ``actor_email`` snapshots
who acted.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0036_staff_audit_log"
down_revision: str | None = "0035_staff_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "staff_audit_log",
        sa.Column(
            "id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", _UUID, nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_audit_log"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_staff_audit_log_actor_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_staff_audit_log_created_at", "staff_audit_log", ["created_at"]
    )
    op.create_index("ix_staff_audit_log_actor_id", "staff_audit_log", ["actor_id"])
    op.create_index("ix_staff_audit_log_action", "staff_audit_log", ["action"])


def downgrade() -> None:
    # Forward-only (Standards §14); provided for completeness.
    op.drop_table("staff_audit_log")
