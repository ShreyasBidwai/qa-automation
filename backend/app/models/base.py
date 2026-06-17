"""Declarative base, shared mixins, and the enum column helper (TRD §3, §14).

Every persisted entity carries a UUID primary key and audit timestamps; every
*project-scoped* entity additionally carries an indexed ``project_id`` FK. Models
hold structure only — no business logic (Standards §5).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TypeVar

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_EnumT = TypeVar("_EnumT", bound=enum.Enum)


class Base(DeclarativeBase):
    pass


def pg_enum(enum_cls: type[_EnumT], name: str) -> SAEnum:
    """A native Postgres enum whose values are the enum *values* (TRD strings)."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda cls: [member.value for member in cls],
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProjectScopedMixin(UUIDPrimaryKeyMixin, TimestampMixin):
    """UUID id + audit columns + an indexed ``project_id`` FK (tenancy root)."""

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
