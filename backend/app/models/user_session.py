"""``sessions`` — a live server-side auth session (B2, ADR-0030).

One row per signed-in bearer token. Only the token's SHA-256 hash is stored, never
the token itself. Sign-out deletes the row (real revocation); ``expires_at`` is
enforced on read. Named ``UserSession`` to avoid clashing with SQLAlchemy ``Session``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Set when a staff member minted this session by impersonating the user (ADR-0071):
    # the actor's id. NULL for a normal login. Makes impersonation auditable and the
    # session identifiable as impersonated — the user's own authority is unchanged (a
    # normal session against the write-only vault, so it stays secret-blind).
    impersonated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
