"""Plans catalog + entitlements (ADR-0069): the seed is present and correct, and the
pure entitlement logic honours NULL-as-unlimited."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.entitlements import Entitlements
from app.models.plan import Plan
from app.repositories.plan_repository import PlanRepository


async def test_plan_catalog_is_seeded(db_session: AsyncSession) -> None:
    keys = {plan.key for plan in await PlanRepository(db_session).list()}
    assert {"free", "team", "business", "enterprise"} <= keys


async def test_free_plan_quotas(db_session: AsyncSession) -> None:
    free = await PlanRepository(db_session).get_by_key("free")
    assert free is not None
    assert free.max_projects == 1
    assert free.included_run_credits_monthly == 50
    assert free.price_per_seat_monthly_usd == 0


async def test_enterprise_is_unlimited_and_custom_priced(
    db_session: AsyncSession,
) -> None:
    ent = await PlanRepository(db_session).get_by_key("enterprise")
    assert ent is not None
    assert ent.max_projects is None  # unlimited
    assert ent.included_run_credits_monthly is None
    assert ent.price_per_seat_monthly_usd is None  # custom / contact us
    assert ent.features.get("saml") is True


async def test_effective_for_unknown_key_falls_back_to_free(
    db_session: AsyncSession,
) -> None:
    plan = await PlanRepository(db_session).effective_for("does-not-exist")
    assert plan is not None and plan.key == "free"


def test_entitlements_enforce_finite_limits() -> None:
    plan = Plan(
        key="team",
        name="Team",
        max_projects=5,
        max_seats=10,
        included_run_credits_monthly=1000,
        max_parallelism=3,
        retention_days=30,
    )
    ent = Entitlements.from_plan(plan)
    assert ent.within_projects(4) is True
    assert ent.within_projects(5) is False  # at the cap, no headroom
    assert ent.within_seats(9) is True
    assert ent.within_credits(999) is True
    assert ent.within_credits(1000) is False


def test_null_quota_means_unlimited() -> None:
    plan = Plan(
        key="enterprise",
        name="Enterprise",
        max_projects=None,
        max_seats=None,
        included_run_credits_monthly=None,
        max_parallelism=25,
        retention_days=365,
    )
    ent = Entitlements.from_plan(plan)
    assert ent.within_projects(10_000) is True
    assert ent.within_seats(10_000) is True
    assert ent.within_credits(10_000) is True
