"""``target_credentials`` — a project's target-app account credentials (ADR-0053).

At most one row per project. ``mode`` records whether runs test a user-provided
specific account or let Polaris provision its own. For a specific account, the
account ``identifier`` (email/mobile — returnable, NOT the secret) is stored and the
account secret is stored ONLY as ``encrypted_secret`` — Fernet ciphertext written by
``app.credentials.crypto``. Plaintext NEVER touches this table.

The secret is write-only: no read/list/payload path ever returns or decrypts it (only
the run-time decrypt-at-use accessor does, in memory). The column is bytea so the
ciphertext is opaque even to a DB inspector.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TargetCredentials(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "target_credentials"
    __table_args__ = (
        # One credentials record per project (the write path upserts on it).
        Index("uq_target_credentials_project_id", "project_id", unique=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # specific_account | polaris_creates (validated string; CredentialMode).
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    # The target account's identifier (email/mobile) — returnable, never the secret.
    # Null for polaris_creates. Redacted before it is ever logged (auth.redact).
    identifier: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # The account secret as Fernet ciphertext — the ONLY form it exists in at rest.
    # Null for polaris_creates. Never returned by any payload; decrypted only at use.
    encrypted_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # The account's TOTP (authenticator-app) shared secret as Fernet ciphertext — the
    # ONLY form it exists in at rest. Present ⇒ runs use the automated TotpStrategy.
    # Never returned by any payload; decrypted only at use (ADR-0053).
    encrypted_totp_secret: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )


__all__ = ["TargetCredentials"]
