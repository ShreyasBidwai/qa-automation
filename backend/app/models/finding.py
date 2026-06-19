"""``findings`` — assembled, consumable bug objects the report is built from (T7.1).

A Finding is the stable contract the rest of Sprint 7 (grouping T7.2, scoring
T7.3, history T7.4) builds on. It is assembled from run ``results`` (it references
the run and the result it covers) and never alters them. It carries the failing
case's oracle_source as its confidence, the expected oracle, the evidence pointer
(the actual is captured there), and the cross-layer location (page→endpoint→table)
resolved from the Brain. ``severity`` and ``status`` are placeholders that T7.3/T7.4
will define. Holds structure only — assembly logic lives in the assembler
(Standards §5).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import FindingLayer, OracleSource

# Placeholder defaults — the real severity/status vocabularies land in T7.3/T7.4.
SEVERITY_UNSET = "unset"
STATUS_OPEN = "open"


class Finding(Base, ProjectScopedMixin):
    __tablename__ = "findings"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The result this finding covers. One per failing result for now; grouping
    # several results into one finding is T7.2 (a new join, not a change here).
    result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    layer: Mapped[FindingLayer] = mapped_column(
        pg_enum(FindingLayer, "finding_layer"), nullable=False
    )
    # Confidence = the failing oracle's source (reuses the existing enum type).
    oracle_source: Mapped[OracleSource] = mapped_column(
        pg_enum(OracleSource, "oracle_source"), nullable=False
    )
    # The oracle's expectation; the actual is captured at evidence_ref.
    expected: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
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
