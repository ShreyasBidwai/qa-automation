"""``generation_signals`` — the self-improvement flywheel's capture spine (ADR-0070).

One row per generated test artifact, joining its INPUT context (route-class, framework,
and the prompt/strategy/model VERSION that produced it) to its OUTCOME (execution result
+ human triage + whether it needed repair/healed + flakiness). The test's own execution
is a FREE label: an ``error`` row is a bad generation, a ``rejected`` triage a bad
oracle. This single append-only log is simultaneously the eval set, the retrieval
corpus (known-good exemplars), and the basis for prompt/strategy optimisation.

Like ``ai_usage``/``incidents``: an observability log keyed by ``project_id``/``run_id``
with NO foreign key — it records what a generation produced + how it fared and must
outlive the entities it references; never mutated after write. ``prompt_version`` /
``strategy`` are load-bearing: without them a quality change cannot be attributed to a
prompt change vs the model vs the customer mix.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GenerationSignal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "generation_signals"
    __table_args__ = (
        # The per-run read (what a run produced + how it fared).
        Index("ix_generation_signals_project_id_run_id", "project_id", "run_id"),
        # The eval/quality read groups by the version that produced the artifact.
        Index("ix_generation_signals_prompt_version", "prompt_version"),
    )

    # Informational references (no FK — see module docstring).
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    test_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # INPUT context — the feature space for retrieval + segmentation.
    route_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # The generation VERSION — attributes a quality change to what actually changed.
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # OUTCOME — the free labels. ``outcome`` is NULL until the artifact is executed.
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    repaired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    healed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    flaky: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    triage: Mapped[str | None] = mapped_column(String(16), nullable=True)

    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
