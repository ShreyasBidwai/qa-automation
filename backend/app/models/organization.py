"""``organizations`` — a team, the tenancy root (B3, ADR-0032).

Projects belong to an org via ``projects.org_id``; users belong to an org via
``organization_members``. ``is_personal`` marks the solo workspace auto-created
for each user on signup, so a single user keeps working without making a team.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # True for the per-user workspace created on signup (ADR-0032); such orgs
    # cannot be deleted and are the default target for `POST /projects`.
    is_personal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Set when platform staff suspend the org (ADR-0068). A suspended org's members
    # keep read access but cannot start runs/ingests (enforced at the enqueue choke
    # point, B3). NULL = active. Reversible; removes nothing (unlike deletion).
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The org's pricing plan (ADR-0069) — references plans.key; defaults to 'free'. A
    # string (not an FK) so the entitlements resolver falls back to 'free' for an
    # absent/unknown key without a join constraint.
    plan_key: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'free'")
    )

    @property
    def is_suspended(self) -> bool:
        return self.suspended_at is not None
