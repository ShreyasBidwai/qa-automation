"""``organization_invites`` — a pending email invitation to join an org (B3).

Reuses B2's reset-token discipline (ADR-0030): only the token's SHA-256 hash is
stored, single-use (``accepted_at``) and expiring (``expires_at``); the raw token
is emailed, never persisted or returned. ``invited_by`` is the actor (known — the
inviter is authenticated), kept for audit and nulled if that user is deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.enums import OrgRole

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class OrganizationInvite(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organization_invites"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The invitee's email (delivery + display); not a foreign key — the person may
    # not have an account yet.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[OrgRole] = mapped_column(pg_enum(OrgRole, "org_role"), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
