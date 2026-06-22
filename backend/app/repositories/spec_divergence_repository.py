"""Repository for ``spec_divergences`` (B9) — project-scoped."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.spec_divergence import SpecDivergence

from .base import ProjectScopedRepository


class SpecDivergenceRepository(ProjectScopedRepository[SpecDivergence]):
    model = SpecDivergence

    async def add_many(
        self, divergences: Sequence[SpecDivergence]
    ) -> list[SpecDivergence]:
        self.session.add_all(list(divergences))
        await self.session.flush()
        return list(divergences)
