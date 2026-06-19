"""auth_challenge_log: encountered login challenges (T4.2a)

Revision ID: 0012_auth_challenge_log
Revises: 0011_navigates_edge_kind
Create Date: 2026-06-18

Forward-only and additive (Standards §14): an ``auth_challenge`` enum + a
project-scoped, append-only ``auth_challenge_log`` table. Each row records a
login-challenge encounter (which challenge a target presented, channel, outcome,
redacted account label) so we can later choose which automated AuthStrategy to
build first. It stores NO secrets (no code/password/full identifier). No
destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_auth_challenge_log"
down_revision: str | None = "0011_navigates_edge_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

auth_challenge = postgresql.ENUM(
    "none", "otp", "2fa", name="auth_challenge", create_type=False
)
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    bind = op.get_bind()
    auth_challenge.create(bind, checkfirst=True)

    op.create_table(
        "auth_challenge_log",
        sa.Column(
            "id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("project_id", _UUID, nullable=False),
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
        sa.Column("target_url", sa.String(length=1024), nullable=False),
        sa.Column("challenge", auth_challenge, nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=True),
        sa.Column("account_label", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_challenge_log"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_auth_challenge_log_project_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_auth_challenge_log_project_id", "auth_challenge_log", ["project_id"]
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_table("auth_challenge_log")
    auth_challenge.drop(op.get_bind(), checkfirst=True)
