"""The ``projects`` table — the tenancy root (TRD §3).

Every other table carries ``project_id`` FK → ``projects.id`` (ProjectScopedMixin).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
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
