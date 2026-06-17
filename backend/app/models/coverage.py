"""``coverage`` — what a run closed per dimension, and its gaps (TRD §3)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import CoverageDimension


class Coverage(Base, ProjectScopedMixin):
    __tablename__ = "coverage"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dimension: Mapped[CoverageDimension] = mapped_column(
        pg_enum(CoverageDimension, "coverage_dimension"), nullable=False
    )
    covered: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    gaps: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
