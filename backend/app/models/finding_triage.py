"""``finding_triage`` — a triage disposition keyed by the LOGICAL issue (ADR-0027).

Triage follows the issue, not the per-run finding row: it is keyed
``(project_id, root_cause_key)`` so a disposition persists across runs and a
won't-fix / false-positive issue stops re-surfacing as fresh every run. Distinct
from ``Finding.status`` (the derived cross-run history, ADR-0023) and from the
per-result ``Triage`` enum. Absent row = ``open``.

Actor attribution (who triaged) is deferred to Tier-2 user auth: ``triaged_at``
is recorded now; a ``triaged_by`` column is a clean one-line additive follow-up
when auth lands — not faked today. Holds structure only (Standards §5).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import TriageStatus


class FindingTriage(Base, ProjectScopedMixin):
    __tablename__ = "finding_triage"
    __table_args__ = (
        # One disposition per logical issue per project (ADR-0027) — the upsert
        # conflict target, enforced at the DB level.
        UniqueConstraint(
            "project_id",
            "root_cause_key",
            name="uq_finding_triage_project_id_root_cause_key",
        ),
    )

    # The stable cross-run issue identity (ADR-0021) the disposition is attached to.
    root_cause_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[TriageStatus] = mapped_column(
        pg_enum(TriageStatus, "triage_status"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When the disposition was last set; stamped on every upsert.
    triaged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
