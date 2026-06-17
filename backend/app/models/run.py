"""``runs`` — an execution of test cases against a target commit (TRD §3)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import RunMode, RunTrigger


class Run(Base, ProjectScopedMixin):
    __tablename__ = "runs"

    trigger: Mapped[RunTrigger] = mapped_column(
        pg_enum(RunTrigger, "run_trigger"), nullable=False
    )
    mode: Mapped[RunMode] = mapped_column(pg_enum(RunMode, "run_mode"), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'pending'")
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
