"""encrypted TOTP secret on target_credentials for automated 2FA (ADR-0053)

Revision ID: 0033_target_totp_secret
Revises: 0032_run_event_screenshot
Create Date: 2026-07-01

Forward-only and additive (Standards §14): a nullable ciphertext column holding the
target account's TOTP (authenticator-app) shared secret, so the automated
TotpStrategy can generate the 2FA code unattended. Encrypted at rest (Fernet, like
``encrypted_secret``); decrypted only at use. No backfill, no destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033_target_totp_secret"
down_revision: str | None = "0032_run_event_screenshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "target_credentials",
        sa.Column("encrypted_totp_secret", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_column("target_credentials", "encrypted_totp_secret")
