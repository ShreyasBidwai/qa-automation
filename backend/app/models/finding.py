"""``findings`` — assembled, consumable bug objects the report is built from.

A Finding is the stable contract the rest of Sprint 7 (scoring T7.3, history
T7.4) builds on. It is assembled from run ``results`` (it references the run and
the results it covers) and never alters them. It carries the group's confidence
(strongest ``oracle_source``), the expected oracle, the evidence pointer (the
actual is captured there), and the cross-layer location (page→endpoint→table)
resolved from the Brain. ``severity`` and ``status`` are placeholders that
T7.3/T7.4 will define.

T7.2 made one Finding group many failing results that share a root cause: the
``root_cause_key`` is the deterministic grouping identity (ADR-0021), unique per
run; ``explains_count`` is how many distinct tests the finding explains; the full
membership is the ``finding_results`` join and ``result_id`` is the retained
representative (T7.1's contract). ``confidence_mixed`` flags a group whose members
disagree on oracle tier. Holds structure only — keying/grouping logic lives in the
assembler (Standards §5).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import FindingLayer, OracleSource

# Placeholder defaults — the real severity/status vocabularies land in T7.3/T7.4.
SEVERITY_UNSET = "unset"
STATUS_OPEN = "open"


class Finding(Base, ProjectScopedMixin):
    __tablename__ = "findings"
    __table_args__ = (
        # One finding per root cause per run (T7.2 grouping invariant, ADR-0021)
        # — enforced at the DB level, and the stable order findings are listed in.
        Index(
            "uq_findings_run_id_root_cause_key",
            "run_id",
            "root_cause_key",
            unique=True,
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The retained representative result (deterministic-first of the group). The
    # full membership is the ``finding_results`` join; T7.1's single-result
    # contract is kept by pointing this at the representative.
    result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Deterministic grouping identity: deepest shared failing node + failure
    # signature (ADR-0021). Always set by the assembler; the '' default only
    # satisfies the additive migration on the (empty) T7.1 table.
    root_cause_key: Mapped[str] = mapped_column(
        String(512), nullable=False, server_default=text("''")
    )
    # How many distinct tests this finding explains (== len(finding_results)).
    explains_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    layer: Mapped[FindingLayer] = mapped_column(
        pg_enum(FindingLayer, "finding_layer"), nullable=False
    )
    # Confidence = the strongest oracle_source in the group (reuses the enum type):
    # one rule-derived/spec-grounded member lifts the whole group.
    oracle_source: Mapped[OracleSource] = mapped_column(
        pg_enum(OracleSource, "oracle_source"), nullable=False
    )
    # True when the group's members disagree on oracle tier (honest confidence).
    confidence_mixed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # The oracle's expectation; the actual is captured at evidence_ref.
    expected: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Opaque ref to a failure screenshot (app.screenshots), copied from the
    # representative result by the assembler. Null when no screenshot was captured;
    # served only via the authorized GET /findings/{id}/screenshot (ADR-0051).
    screenshot_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Cross-layer location resolved from the Brain (page/endpoints/tables).
    location: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    severity: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text(f"'{SEVERITY_UNSET}'")
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text(f"'{STATUS_OPEN}'")
    )
