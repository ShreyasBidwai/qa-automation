"""``test_scripts`` — generated portable test code for a test case (TRD §3)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import Framework


class TestScript(Base, ProjectScopedMixin):
    __tablename__ = "test_scripts"

    test_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    framework: Mapped[Framework] = mapped_column(
        pg_enum(Framework, "framework"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    deterministic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
