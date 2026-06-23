"""``results`` — the outcome of one test case within a run (TRD §3)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import Outcome, Triage


class Result(Base, ProjectScopedMixin):
    __tablename__ = "results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    outcome: Mapped[Outcome] = mapped_column(
        pg_enum(Outcome, "outcome"), nullable=False
    )
    triage: Mapped[Triage | None] = mapped_column(
        pg_enum(Triage, "triage"), nullable=True
    )
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Opaque ref to a failure screenshot (app.screenshots), captured at execution for
    # a failing result; the assembler copies it onto the finding. Null otherwise.
    screenshot_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # The runner's failure detail (assertion text / router error), persisted so the
    # self-healing classifier (B8) can split location vs assertion failures after
    # the run. Null for passes and for results predating B8.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
