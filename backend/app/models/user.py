"""``users`` — an authenticated person (B2). The new ownership/tenancy root.

Email is stored normalized (lower-cased, by the service) and uniquely indexed.
``password_hash`` is an argon2id hash (ADR-0030); the plaintext never persists.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.enums import StaffRole

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


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
    # NOT an org role. Superseded by ``staff_role`` (ADR-0068); kept during the
    # transition. Granted out of band (DB/seed); no API sets it.
    is_operator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Instance-level staff role for the cross-tenant operator/admin console
    # (ADR-0068). NULL = not staff. The permission matrix lives in
    # ``app.core.staff_permissions``. Granted only by a superadmin via the admin
    # API (or seed); never an org role.
    staff_role: Mapped[StaffRole | None] = mapped_column(
        pg_enum(StaffRole, "staff_role"), nullable=True
    )
