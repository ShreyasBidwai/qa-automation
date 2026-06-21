"""``organizations`` — a team, the tenancy root (B3, ADR-0032).

Projects belong to an org via ``projects.org_id``; users belong to an org via
``organization_members``. ``is_personal`` marks the solo workspace auto-created
for each user on signup, so a single user keeps working without making a team.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, text
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
