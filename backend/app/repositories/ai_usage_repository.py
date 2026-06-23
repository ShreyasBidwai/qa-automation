"""Repository for ``ai_usage`` — per-invocation usage + per-run rollup (ADR-0049).

A standalone repository (like ``IncidentRepository``): ``ai_usage`` is an
observability log keyed by ``project_id``/``run_id`` rather than a project-scoped
entity. The per-run aggregate is COMPUTED over the persisted per-call records — the
records are the single source of truth, so the totals/per-phase/per-model rollup can
never drift from them (no denormalized summary to keep in sync). One run's record
set is small, so the rollup is a single read + an in-memory fold.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_usage import AiUsage


@dataclass(frozen=True)
class UsageBucket:
    """Summed usage for one slice (a phase or a model)."""

    call_count: int = 0
    total_cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _MutableBucket:
    call_count: int = 0
    total_cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, record: AiUsage) -> None:
        self.call_count += 1
        self.total_cost_usd += _num(record.total_cost_usd)
        self.input_tokens += _int(record.input_tokens)
        self.output_tokens += _int(record.output_tokens)
        self.cache_creation_input_tokens += _int(record.cache_creation_input_tokens)
        self.cache_read_input_tokens += _int(record.cache_read_input_tokens)

    def freeze(self) -> UsageBucket:
        return UsageBucket(
            call_count=self.call_count,
            total_cost_usd=self.total_cost_usd,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
        )


@dataclass(frozen=True)
class RunUsageTotals:
    """The per-run rollup: totals + per-phase + per-model, computed from records.

    ``total_cost_usd`` is the sum of the ACTUAL billed costs the CLI reported for the
    run's invocations (includes harness/cache — see ADR-0049). Unavailable records
    (parse failed) contribute to ``call_count``/``unavailable_call_count`` but add
    zero cost/tokens (their columns are NULL).
    """

    run_id: uuid.UUID
    call_count: int
    available_call_count: int
    unavailable_call_count: int
    error_count: int
    total_cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    per_phase: dict[str, UsageBucket] = field(default_factory=dict)
    per_model: dict[str, UsageBucket] = field(default_factory=dict)


def _int(value: int | None) -> int:
    return value if value is not None else 0


def _num(value: Decimal | float | None) -> float:
    return float(value) if value is not None else 0.0


class AiUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_all(self, records: Iterable[AiUsage]) -> list[AiUsage]:
        items = list(records)
        if not items:
            return []
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def list_for_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[AiUsage]:
        """A run's usage records, oldest first (deterministic)."""
        stmt = (
            select(AiUsage)
            .where(AiUsage.project_id == project_id, AiUsage.run_id == run_id)
            .order_by(AiUsage.created_at, AiUsage.id)
        )
        return list((await self.session.scalars(stmt)).all())

    async def aggregate_for_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> RunUsageTotals:
        """Totals + per-phase + per-model rollup for a run (computed from records)."""
        return aggregate(run_id, await self.list_for_run(project_id, run_id))


def aggregate(run_id: uuid.UUID, records: Sequence[AiUsage]) -> RunUsageTotals:
    """Fold a run's usage records into the per-run aggregate (pure, testable)."""
    totals = _MutableBucket()
    per_phase: dict[str, _MutableBucket] = {}
    per_model: dict[str, _MutableBucket] = {}
    available = unavailable = errors = 0

    for record in records:
        totals.add(record)
        per_phase.setdefault(record.phase, _MutableBucket()).add(record)
        per_model.setdefault(record.model or "unknown", _MutableBucket()).add(record)
        if record.usage_available:
            available += 1
        else:
            unavailable += 1
        if record.is_error:
            errors += 1

    return RunUsageTotals(
        run_id=run_id,
        call_count=totals.call_count,
        available_call_count=available,
        unavailable_call_count=unavailable,
        error_count=errors,
        total_cost_usd=totals.total_cost_usd,
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        cache_creation_input_tokens=totals.cache_creation_input_tokens,
        cache_read_input_tokens=totals.cache_read_input_tokens,
        per_phase={k: v.freeze() for k, v in per_phase.items()},
        per_model={k: v.freeze() for k, v in per_model.items()},
    )
