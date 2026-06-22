"""``test_heals`` — flagged, confirmable addressing heals (B8, ADR-0040).

One row per proposed heal: a location failure whose target was re-resolved against
the current Brain. It records the before/after addressing, the rationale and
confidence behind the re-binding, and the re-addressed script — but does NOT touch
the live test until a human confirms (flagged, never silent). ``status`` carries the
trust state: ``proposed`` is lower-trust (awaiting review), ``confirmed`` applies the
re-addressing and restores trust, ``rejected`` discards it.

Heals never change assertions (enforced structurally in ``app.healing.apply``), so a
heal is always addressing-only by construction.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin

STATUS_PROPOSED = "proposed"  # healed, lower-trust, awaiting a human decision
STATUS_CONFIRMED = "confirmed"  # human-confirmed → re-addressing applied, trusted
STATUS_REJECTED = "rejected"  # human-rejected → discarded, the test is untouched


class TestHeal(Base, ProjectScopedMixin):
    __tablename__ = "test_heals"
    __table_args__ = (
        # Idempotency: the same logical heal (a test re-addressed the same way)
        # is recorded once. Re-scanning a run, or a later run surfacing the same
        # drift, is a no-op rather than a duplicate.
        UniqueConstraint(
            "test_case_id",
            "before_addr",
            "after_addr",
            name="uq_test_heals_dedup",
        ),
        Index("ix_test_heals_project_id_run_id", "project_id", "run_id"),
        Index("ix_test_heals_project_id_status", "project_id", "status"),
    )

    # The run whose results surfaced this heal (null-safe: SET NULL if pruned).
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # What kind of addressing was re-bound, and why we were allowed to.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # "route_rebind"
    failure_class: Mapped[str] = mapped_column(String(16), nullable=False)  # "location"
    before_addr: Mapped[str] = mapped_column(String(1024), nullable=False)
    after_addr: Mapped[str] = mapped_column(String(1024), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'high'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'proposed'")
    )
    # The re-addressed script — assertion-identical to the original. Applied to the
    # live test only on confirmation.
    healed_code: Mapped[str] = mapped_column(Text, nullable=False)
    # Who confirmed/rejected, and when (null while still proposed).
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
