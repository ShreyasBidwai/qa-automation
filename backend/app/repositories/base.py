"""Generic project-scoped repository (Standards §5, §14).

EVERY query is filtered by ``project_id`` — there are no global reads. Concrete
repositories set ``model`` and add entity-specific, still-scoped queries.
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import ProjectScopedMixin

ModelT = TypeVar("ModelT", bound=ProjectScopedMixin)


class ProjectScopedRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get(self, project_id: uuid.UUID, entity_id: uuid.UUID) -> ModelT | None:
        stmt = select(self.model).where(
            self.model.project_id == project_id,
            self.model.id == entity_id,
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def list(self, project_id: uuid.UUID) -> list[ModelT]:
        stmt = (
            select(self.model)
            .where(self.model.project_id == project_id)
            .order_by(self.model.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count(self, project_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.project_id == project_id)
        )
        return int(await self.session.scalar(stmt) or 0)

    async def delete(self, project_id: uuid.UUID, entity_id: uuid.UUID) -> bool:
        entity = await self.get(project_id, entity_id)
        if entity is None:
            return False
        await self.session.delete(entity)
        await self.session.flush()
        return True
