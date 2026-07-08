"""Entitlements — what a plan permits (ADR-0069).

Pure data logic, no DB and no HTTP — the commercial analogue of
``app.core.permissions``. A NULL quota means UNLIMITED. The org→plan resolution (with
the free-tier fallback) lives in ``PlanRepository``; the *decisions* are here so they
are cheap to unit-test and reused identically by the quota guard (B3) and the billing
surfaces (B4/B5).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.plan import Plan

# The tier an org falls back to when it has no (or an unknown) plan_key.
FREE_PLAN_KEY = "free"


@dataclass(frozen=True)
class Entitlements:
    """A plan's quotas as a plain, comparable value object. NULL = unlimited."""

    max_projects: int | None
    max_seats: int | None
    included_run_credits_monthly: int | None
    max_parallelism: int
    retention_days: int

    @classmethod
    def from_plan(cls, plan: Plan) -> Entitlements:
        return cls(
            max_projects=plan.max_projects,
            max_seats=plan.max_seats,
            included_run_credits_monthly=plan.included_run_credits_monthly,
            max_parallelism=plan.max_parallelism,
            retention_days=plan.retention_days,
        )

    def within_projects(self, current: int) -> bool:
        """May a project be added given ``current`` existing ones?"""
        return self.max_projects is None or current < self.max_projects

    def within_seats(self, current: int) -> bool:
        """May a seat be added given ``current`` existing members?"""
        return self.max_seats is None or current < self.max_seats

    def within_credits(self, used: int) -> bool:
        """Is there run-credit headroom given ``used`` this period?"""
        return (
            self.included_run_credits_monthly is None
            or used < self.included_run_credits_monthly
        )
