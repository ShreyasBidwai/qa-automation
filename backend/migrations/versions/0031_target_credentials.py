"""target-account credentials at rest (encrypted secret): target_credentials (ADR-0053)

Revision ID: 0031_target_credentials
Revises: 0030_finding_screenshot
Create Date: 2026-06-24

Forward-only and additive (Standards §14): at most one credentials row per project
(unique ``project_id``, ON DELETE CASCADE). ``mode`` is a validated string (no enum).
The account secret is stored ONLY as ``encrypted_secret`` (bytea = Fernet ciphertext,
written by app.credentials.crypto) — plaintext never reaches this table. The
``identifier`` (email/mobile) is returnable, not the secret. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0031_target_credentials"
down_revision: str | None = "0030_finding_screenshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "target_credentials",
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
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("identifier", sa.String(length=512), nullable=True),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_target_credentials_project_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_target_credentials"),
    )
    op.create_index(
        "uq_target_credentials_project_id",
        "target_credentials",
        ["project_id"],
        unique=True,
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index(
        "uq_target_credentials_project_id", table_name="target_credentials"
    )
    op.drop_table("target_credentials")
