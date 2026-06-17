"""``test_cases`` — versioned, project-scoped test cases (TRD §3)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import AuthoredBy, OracleSource, TestLayer, TestType


class TestCase(Base, ProjectScopedMixin):
    __tablename__ = "test_cases"
    __table_args__ = (Index("ix_test_cases_project_id_type", "project_id", "type"),)

    type: Mapped[TestType] = mapped_column(
        pg_enum(TestType, "test_type"), nullable=False
    )
    layer: Mapped[TestLayer] = mapped_column(
        pg_enum(TestLayer, "test_layer"), nullable=False
    )
    # References a Brain model_nodes.id once that table exists; FK deferred until then.
    target_node: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    preconditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    steps: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    expected: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    oracle_source: Mapped[OracleSource] = mapped_column(
        pg_enum(OracleSource, "oracle_source"), nullable=False
    )
    authored_by: Mapped[AuthoredBy] = mapped_column(
        pg_enum(AuthoredBy, "authored_by"), nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requirement_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'draft'")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
