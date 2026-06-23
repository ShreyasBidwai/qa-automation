"""``runs`` — an execution of test cases against a target commit (TRD §3)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import RunMode, RunTrigger


class Run(Base, ProjectScopedMixin):
    __tablename__ = "runs"
    __table_args__ = (
        # A friendly per-project run number ("#482"), unique within a project. NULL
        # is allowed (multiple NULLs are distinct in Postgres) for rows created
        # outside the assignment path; real runs always carry one.
        Index("uq_runs_project_id_run_number", "project_id", "run_number", unique=True),
    )

    # Per-project monotonic run number, assigned at creation (RunRepository
    # .next_run_number) and stable thereafter. Nullable so the column is additive.
    run_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
