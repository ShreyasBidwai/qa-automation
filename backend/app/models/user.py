"""``users`` — an authenticated person (B2). The new ownership/tenancy root.

Email is stored normalized (lower-cased, by the service) and uniquely indexed.
``password_hash`` is an argon2id hash (ADR-0030); the plaintext never persists.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    # Optional display name (B3 account profile); set/edited via PATCH /auth/me.
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Instance-level operator flag (B4, ADR-0035) — cross-tenant ops visibility,
    # NOT an org role. Granted out of band (DB/seed); no API sets it.
    is_operator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
