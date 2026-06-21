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
    # The owning user (B2, ADR-0031). NULL = legacy/shared (pre-auth data); new
    # projects are created owned. ON DELETE SET NULL → a deleted user's projects
    # become shared rather than cascade-deleting their work.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
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
