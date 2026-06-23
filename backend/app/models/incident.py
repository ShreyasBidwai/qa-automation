"""``incidents`` — structured capture of Polaris's own internal failures (B-dev-suite).

When Polaris fails during its work (a run errors, ingest fails, a provider call
dies, the orchestrator/a job throws), the failure is recorded here with enough
context to diagnose it WITHOUT decoding raw logs: the phase it happened in, the
project/run when applicable, the exception type + message + traceback, and a stable
``fingerprint`` (the root-cause-key idea pointed inward) so the SAME failure groups.

NOT project-scoped: ``project_id`` is nullable (a job-infra or provider failure may
have no project) and intentionally carries NO foreign key — incidents are an
operator diagnostic log that outlives the entities they reference (a deleted project
must not erase the record of why it failed). Read-only to operators; never mutated.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Incident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "incidents"
    __table_args__ = (
        # Grouping: the same failure (same fingerprint) over time.
        Index("ix_incidents_fingerprint", "fingerprint"),
        # The list view is newest-first, optionally filtered by phase/project.
        Index("ix_incidents_created_at", "created_at"),
        Index("ix_incidents_phase", "phase"),
        Index("ix_incidents_project_id", "project_id"),
    )

    # Where it happened: ingest / generation / execution / orchestrator / job /
    # provider (a validated string; capture maps the failing seam to one of these).
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    # Finer component hint (e.g. "job:run", a worker id) — optional context.
    component: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Informational references (no FK — see module docstring). Nullable when N/A.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    exception_type: Mapped[str] = mapped_column(String(256), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stable hash over exception type + normalized raise location (fingerprint.py).
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
