"""Repository for the ``plans`` catalog (ADR-0069).

Standalone (plans are a small global catalog, not tenant-scoped). Resolves an org's
effective plan with the free-tier fallback so an absent/unknown ``plan_key`` never
crashes a quota check.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.entitlements import FREE_PLAN_KEY
from app.models.plan import Plan


class PlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_key(self, key: str) -> Plan | None:
        stmt = select(Plan).where(Plan.key == key)
        return (await self.session.scalars(stmt)).one_or_none()

    async def list(self, *, public_only: bool = False) -> list[Plan]:
        stmt = select(Plan).order_by(Plan.sort_order, Plan.key)
        if public_only:
            stmt = stmt.where(Plan.is_public.is_(True))
        return list((await self.session.scalars(stmt)).all())

    async def effective_for(self, plan_key: str) -> Plan | None:
        """The plan for ``plan_key``, falling back to the free tier for an unknown key.
        Returns None only if the catalog is unseeded (free tier missing)."""
        plan = await self.get_by_key(plan_key)
        if plan is not None:
            return plan
        return await self.get_by_key(FREE_PLAN_KEY)
