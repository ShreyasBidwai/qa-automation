"""``finding_results`` — the many-to-one membership join (T7.2).

One Finding groups the failing results that share a root cause (ADR-0021); each
row here ties one Result to the Finding it belongs to. ``explains_count`` on the
Finding equals the number of these rows. Project-scoped like everything else; a
``(finding_id, result_id)`` pair is unique so re-assembly cannot double-count.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin


class FindingResult(Base, ProjectScopedMixin):
    __tablename__ = "finding_results"
    __table_args__ = (
        UniqueConstraint(
            "finding_id", "result_id", name="uq_finding_results_finding_id_result_id"
        ),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
