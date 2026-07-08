"""Repository for ``generation_signals`` (ADR-0070).

Append-only capture + the eval aggregate the flywheel dashboard reads. Standalone — an
observability log, like ``IncidentRepository`` / ``AiUsageRepository``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_signal import GenerationSignal


@dataclass(frozen=True)
class GenerationQuality:
    """The eval aggregate over a window (optionally one prompt version). The dashboard
    (C6) derives a composite quality index from these — pass-rate alone must never be
    the target (it rewards trivial always-pass tests); false positives + repair/heal are
    the counterweights (ADR-0070)."""

    total: int
    by_outcome: dict[str, int]  # pass / fail / error / skipped (executed rows only)
    repaired: int
    healed: int
    flaky: int
    triaged: int
    triage_rejected: int  # false positives — a bad-oracle signal


class GenerationSignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        project_id: uuid.UUID,
        prompt_version: str,
        strategy: str,
        run_id: uuid.UUID | None = None,
        test_case_id: uuid.UUID | None = None,
        route_class: str | None = None,
        framework: str | None = None,
        target_kind: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        outcome: str | None = None,
        repaired: bool = False,
        healed: bool = False,
        flaky: bool = False,
        triage: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> GenerationSignal:
        """Append one immutable generation-outcome row."""
        signal = GenerationSignal(
            project_id=project_id,
            run_id=run_id,
            test_case_id=test_case_id,
            route_class=route_class,
            framework=framework,
            target_kind=target_kind,
            prompt_version=prompt_version,
            strategy=strategy,
            model=model,
            provider=provider,
            outcome=outcome,
            repaired=repaired,
            healed=healed,
            flaky=flaky,
            triage=triage,
            detail=detail or {},
        )
        self.session.add(signal)
        await self.session.flush()
        return signal

    async def quality_summary(
        self, *, since: datetime, prompt_version: str | None = None
    ) -> GenerationQuality:
        """The eval aggregate since ``since`` (optionally scoped to one prompt version —
        the basis for A/B'ing a prompt/strategy change)."""
        conds = [GenerationSignal.created_at >= since]
        if prompt_version is not None:
            conds.append(GenerationSignal.prompt_version == prompt_version)

        totals_stmt = select(
            func.count(),
            func.count().filter(GenerationSignal.repaired.is_(True)),
            func.count().filter(GenerationSignal.healed.is_(True)),
            func.count().filter(GenerationSignal.flaky.is_(True)),
            func.count().filter(GenerationSignal.triage.isnot(None)),
            func.count().filter(GenerationSignal.triage == "rejected"),
        ).where(*conds)
        total, repaired, healed, flaky, triaged, rejected = (
            await self.session.execute(totals_stmt)
        ).one()

        outcome_stmt = (
            select(GenerationSignal.outcome, func.count())
            .where(*conds, GenerationSignal.outcome.isnot(None))
            .group_by(GenerationSignal.outcome)
        )
        by_outcome = {
            outcome: count
            for outcome, count in (await self.session.execute(outcome_stmt))
        }
        return GenerationQuality(
            total=total,
            by_outcome=by_outcome,
            repaired=repaired,
            healed=healed,
            flaky=flaky,
            triaged=triaged,
            triage_rejected=rejected,
        )
