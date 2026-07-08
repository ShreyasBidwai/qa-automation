"""Per-org AI cost + usage rollup for the billing surfaces (ADR-0069, B2).

Sums the already-captured per-invocation cost (ADR-0049) across an org's projects over
a period — the cost-to-serve a tenant, the basis for run-credit debiting and the
operator margin view. The org is derived via ``ai_usage.project_id -> projects.org_id``
(no ``org_id`` is stored on ``ai_usage`` — the join is the source of truth, and unlike
a denormalized column it never goes stale). Reads the control-plane DB only;
cross-tenant by design, gated at the API by staff RBAC (VIEW_BILLING).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_usage import AiUsage
from app.models.project import Project


@dataclass(frozen=True)
class ModelCost:
    model: str | None
    invocation_count: int
    total_cost_usd: Decimal


@dataclass(frozen=True)
class OrgUsageSummary:
    total_cost_usd: Decimal
    invocation_count: int
    run_count: int
    input_tokens: int
    output_tokens: int
    by_model: list[ModelCost] = field(default_factory=list)


class OrgUsageReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, org_id: uuid.UUID, *, since: datetime) -> OrgUsageSummary:
        """Cost + token + run rollup for an org's usage since ``since``."""
        totals_stmt = (
            select(
                func.coalesce(func.sum(AiUsage.total_cost_usd), 0),
                func.count(),
                func.count(func.distinct(AiUsage.run_id)),
                func.coalesce(func.sum(AiUsage.input_tokens), 0),
                func.coalesce(func.sum(AiUsage.output_tokens), 0),
            )
            .select_from(AiUsage)
            .join(Project, Project.id == AiUsage.project_id)
            .where(Project.org_id == org_id, AiUsage.created_at >= since)
        )
        total_cost, invocations, runs, in_tokens, out_tokens = (
            await self.session.execute(totals_stmt)
        ).one()

        by_model_stmt = (
            select(
                AiUsage.model,
                func.count(),
                func.coalesce(func.sum(AiUsage.total_cost_usd), 0),
            )
            .join(Project, Project.id == AiUsage.project_id)
            .where(Project.org_id == org_id, AiUsage.created_at >= since)
            .group_by(AiUsage.model)
            .order_by(func.coalesce(func.sum(AiUsage.total_cost_usd), 0).desc())
        )
        by_model = [
            ModelCost(
                model=model,
                invocation_count=count,
                total_cost_usd=Decimal(str(cost)),
            )
            for model, count, cost in (await self.session.execute(by_model_stmt))
        ]
        return OrgUsageSummary(
            total_cost_usd=Decimal(str(total_cost)),
            invocation_count=invocations,
            run_count=runs,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            by_model=by_model,
        )
