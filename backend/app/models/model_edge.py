"""``model_edges`` — directed, confidence-weighted edges between nodes (TRD §3, §7).

Both endpoints reference ``model_nodes``; tenancy (same-project endpoints) is
enforced in the repository (Standards §5 — models hold structure only).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import EdgeKind


class ModelEdge(Base, ProjectScopedMixin):
    __tablename__ = "model_edges"
    __table_args__ = (
        Index("ix_model_edges_src_node_id", "src_node_id"),
        Index("ix_model_edges_dst_node_id", "dst_node_id"),
        # Idempotent re-ingestion is keyed on (project_id, src, dst, kind).
        UniqueConstraint(
            "project_id",
            "src_node_id",
            "dst_node_id",
            "kind",
            name="uq_model_edges_project_src_dst_kind",
        ),
    )

    src_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    dst_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[EdgeKind] = mapped_column(
        pg_enum(EdgeKind, "edge_kind"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("1.0")
    )
