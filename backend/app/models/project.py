"""The ``projects`` table — the tenancy root (TRD §3).

Every other table carries ``project_id`` FK → ``projects.id`` (ProjectScopedMixin).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    # The owning organization (B3, ADR-0032) — the tenancy root. Access is decided
    # by the caller's membership + role in this org (ADR-0033). ON DELETE CASCADE:
    # deleting an org removes its projects (owner-gated; personal orgs can't be
    # deleted).
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Who first created the project (B2's owner_id, renamed in 0019). Provenance
    # only — it does NOT govern access (org_id does). ON DELETE SET NULL so a
    # deleted creator doesn't cascade-delete the project.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The crawl / E2E target base URL — a first-class operational field (Sprint B1).
    app_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Other flexible config (repo_url, auth_config_ref, stack, …) stays here.
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Soft-delete marker (ADR-0029): set on DELETE; reads exclude non-null rows.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
