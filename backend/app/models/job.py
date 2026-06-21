"""``jobs`` — the durable job queue (B4, ADR-0034).

One row per enqueued ingest/run, the single source of truth for job lifecycle so
work survives a restart. Claimed with ``FOR UPDATE SKIP LOCKED`` (see
``JobQueue``); ``payload`` holds everything needed to run the job after a restart;
``attempts``/``available_at`` drive retry-with-backoff; ``locked_at``/``locked_by``
are the worker lease used to surface stuck jobs to the operator view.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.enums import JobKind, JobStatus

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class Job(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "jobs"

    kind: Mapped[JobKind] = mapped_column(pg_enum(JobKind, "job_kind"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        nullable=False,
        server_default=JobStatus.QUEUED.value,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The run mode for run jobs (display/poll); None for ingest.
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Everything needed to execute after a restart (the serialized run request).
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Orchestrator result (run jobs) / failure type (no secrets).
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Retry-with-backoff: bump attempts on claim; re-queue with a future
    # ``available_at`` until ``max_attempts``.
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # Worker lease: when/who claimed it (stuck-job detection for the operator view).
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
