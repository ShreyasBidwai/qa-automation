"""``organization_members`` — a user's membership-with-role in an org (B3).

One row per (org, user); the ``role`` (ADR-0033) governs what the user may do in
that org. Both FKs cascade: deleting an org or a user removes the membership.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.enums import OrgRole

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class OrganizationMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_organization_members_org_user"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[OrgRole] = mapped_column(pg_enum(OrgRole, "org_role"), nullable=False)
