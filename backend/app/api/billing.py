"""Customer-facing billing / plans (ADR-0069).

The public plan catalog for the in-app pricing + upgrade view. Authenticated (any
signed-in user); an org's plan *assignment* is a staff action on the admin router
(MANAGE_BILLING). No secret or payment data here — Stripe (a later slice) integrates
without storing card data in our DB.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan
from app.repositories.plan_repository import PlanRepository

from .deps import CurrentUser, get_session
from .schemas import PlanItem, PlanListResponse

router = APIRouter(prefix="/api/v1", tags=["billing"])


def _plan_item(plan: Plan) -> PlanItem:
    price = plan.price_per_seat_monthly_usd
    return PlanItem(
        key=plan.key,
        name=plan.name,
        price_per_seat_monthly_usd=float(price) if price is not None else None,
        included_run_credits_monthly=plan.included_run_credits_monthly,
        max_projects=plan.max_projects,
        max_seats=plan.max_seats,
        max_parallelism=plan.max_parallelism,
        retention_days=plan.retention_days,
        features=plan.features,
    )


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanListResponse:
    """The public plan catalog (sorted), for the pricing / upgrade view (ADR-0069)."""
    plans = await PlanRepository(session).list(public_only=True)
    return PlanListResponse(items=[_plan_item(plan) for plan in plans])
