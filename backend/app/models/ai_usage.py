"""``ai_usage`` — per-invocation AI usage + actual billed cost (ADR-0049).

One row per model invocation made on a run's behalf, attributed to the run and the
phase (generation / triage / …). ``total_cost_usd`` is the REAL billed cost of the
``claude -p`` invocation as reported by the CLI — which INCLUDES the Claude Code
harness/system-prompt/tool-schema tokens and prompt caching, so it is the honest
"what this call cost us to invoke", not a clean prompt+completion figure, and it
varies with cache warmth. Cache-read and cache-creation tokens are stored separately
so the breakdown stays legible.

Capture is best-effort: when the CLI envelope can't be parsed, ``usage_available``
is False and the token/cost columns are NULL (the call still succeeded). Like
``incidents``, this is an observability log keyed by ``project_id`` + ``run_id``
without a foreign key — it records what an invocation cost and must outlive the
entities it references; never mutated after write.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Money precision for reported CLI costs: 8 fractional digits comfortably holds the
# CLI's ~7-significant-figure dollar values (e.g. 0.01740890) without float drift.
_COST = Numeric(14, 8)


class AiUsage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_usage"
    __table_args__ = (
        # The per-run read (records + aggregate) is the access path.
        Index("ix_ai_usage_project_id_run_id", "project_id", "run_id"),
    )

    # Informational references (no FK — see module docstring). Always set at persist
    # time (records are buffered during the phase, then flushed once the run exists).
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # The phase the invocation served: generation / triage / … (validated string).
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    # The model requested (e.g. "claude-opus-4-8"), or "stub" for the test provider.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Token breakdown (NULL when usage was unavailable). cache_* kept separate so the
    # invocation's cache behavior is legible, not folded into input_tokens.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_creation_input_tokens: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    cache_read_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Actual billed cost of the invocation (see module docstring) + the per-model
    # attribution hint from the CLI's modelUsage rollup. NULL when unavailable.
    total_cost_usd: Mapped[float | None] = mapped_column(_COST, nullable=True)
    model_cost_usd: Mapped[float | None] = mapped_column(_COST, nullable=True)

    # Best-effort flags: usage_available=False means parsing failed (cost/tokens
    # NULL); is_error surfaces the envelope's own is_error honestly.
    usage_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_error: Mapped[bool] = mapped_column(Boolean, nullable=False)


__all__ = ["AiUsage"]
