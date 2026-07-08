"""``staff_audit_log`` — an immutable record of every cross-tenant staff action
(ADR-0068).

Append-only: each row is one action a platform-staff member took in the operator
console (grant a role, retry a job, suspend an org, adjust billing, impersonate).
Cross-tenant like ``incidents`` — the ``target_*`` references are informational and
carry NO foreign key, so the log outlives the entities it references (a deleted org
must not erase the record of who suspended it, or why). The ``actor_id`` FK is
``SET NULL`` on user delete so the row survives; ``actor_email`` snapshots who it
was. Never updated or deleted — the trail is the point.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StaffAuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff_audit_log"
    __table_args__ = (
        # The list view is newest-first, optionally filtered by actor/action.
        Index("ix_staff_audit_log_created_at", "created_at"),
        Index("ix_staff_audit_log_actor_id", "actor_id"),
        Index("ix_staff_audit_log_action", "action"),
    )

    # The staff member who acted. SET NULL on delete so the record survives; the
    # email is snapshotted so a nulled actor is still identifiable.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False)
    # A stable, dotted action verb: "staff_role.grant", "job.retry", "org.suspend".
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # What was acted on (informational, no FK — outlives the target). Nullable when
    # the action targets no single entity.
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Structured context (before/after, reason, args) — NEVER secrets.
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
