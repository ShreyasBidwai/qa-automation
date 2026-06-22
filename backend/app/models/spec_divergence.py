"""``spec_divergences`` — concrete spec-vs-code divergences (B9, ADR-0039).

A distinct, honest signal: a document references something concrete (an endpoint)
that the code Brain lacks. Both sides are recorded ("spec says X, code shows Y");
we do NOT adjudicate which is wrong (stale doc vs real gap — a human decides).
Only high-confidence, concrete references are stored (confidence-gated upstream).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin


class SpecDivergence(Base, ProjectScopedMixin):
    __tablename__ = "spec_divergences"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # e.g. "endpoint_missing".
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    spec_reference: Mapped[str] = mapped_column(String(512), nullable=False)  # "X"
    code_observation: Mapped[str] = mapped_column(String(512), nullable=False)  # "Y"
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)  # the doc snippet
    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'high'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'open'")
    )
