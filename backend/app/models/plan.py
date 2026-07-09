"""``plans`` — the pricing / entitlement catalog (ADR-0069).

One row per tier (free / team / business / enterprise), keyed by a stable ``key``.
The columns carry the entitlements a plan grants; NULL on a quota means UNLIMITED, and
a NULL ``price_per_seat_monthly_usd`` means custom / "contact us" (enterprise). A table
— not a hardcoded enum — so pricing + quotas are tunable and admin-manageable without a
migration. Seeded by migration 0038; ``organizations.plan_key`` references ``key``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# List price precision — plain dollars-and-cents (unlike the 8-dp CLI cost figures).
_PRICE = Numeric(10, 2)


class Plan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "plans"

    key: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Per-seat monthly list price; NULL = custom / "contact us".
    price_per_seat_monthly_usd: Mapped[float | None] = mapped_column(
        _PRICE, nullable=True
    )
    # Entitlements / quotas — NULL = unlimited.
    included_run_credits_monthly: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    max_projects: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_parallelism: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    # Flexible feature flags (sso, saml, priority_support, …).
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Whether the tier appears on the public pricing page (hides internal/legacy).
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
