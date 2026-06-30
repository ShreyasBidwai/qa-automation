"""``run_events`` — ordered run-progress events for the live run view (ADR-0050).

One row per progress event emitted as a run executes (select → generate → execute
step-by-step → review). Like ``incidents`` / ``ai_usage`` it is an observability log
keyed by ``run_id`` with no foreign key — it records what happened during a run and
must outlive the entities it references; never mutated after write.

``run_id`` is the durable run handle the API exposes (the RUN job id — every
``/runs/{run_id}`` route resolves that id). ``seq`` is a per-run monotonic counter
giving deterministic ordering; the unique ``(run_id, seq)`` index enforces it and
backstops against duplicates. ``detail`` is optional structured context (which
endpoint/page/test, duration, …).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RunEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "run_events"
    __table_args__ = (
        # Deterministic ordering + dedup; also the per-run read path (seq cursor).
        Index("uq_run_events_run_id_seq", "run_id", "seq", unique=True),
    )

    # Informational references (no FK — see module docstring). run_id = the API run
    # id (the RUN job id); project_id scopes the authorized read.
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Deterministic per-run ordering.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    # The journey: phase (run/select/generate/execute/review), a human step label,
    # and the step's status (started/passed/failed/skipped) — all validated strings.
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    step: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Optional structured context (endpoint/page/test identity, duration, counts, …).
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Optional opaque screenshot ref (ADR-0051) for the step — a crawled page's frame
    # or a failing test's capture. The bytes are served ONLY through the authorized
    # ``GET /runs/{run_id}/events/screenshot?seq=N`` endpoint, never exposed as a path;
    # the client sees only ``has_screenshot`` (a bool), never this storage key.
    screenshot_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)


__all__ = ["RunEvent"]
