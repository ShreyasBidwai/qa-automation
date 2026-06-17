"""Repository for ``model_nodes`` (TRD §3, §7) — project-scoped, idempotent."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.enums import NodeKind
from app.models.model_node import ModelNode

from .base import ProjectScopedRepository


class NodeRepository(ProjectScopedRepository[ModelNode]):
    model = ModelNode

    async def get_by_key(
        self, project_id: uuid.UUID, kind: NodeKind, name: str
    ) -> ModelNode | None:
        stmt = select(ModelNode).where(
            ModelNode.project_id == project_id,
            ModelNode.kind == kind,
            ModelNode.name == name,
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def list_by_kind(
        self, project_id: uuid.UUID, kind: NodeKind
    ) -> list[ModelNode]:
        stmt = (
            select(ModelNode)
            .where(ModelNode.project_id == project_id, ModelNode.kind == kind)
            .order_by(ModelNode.name)
        )
        return list((await self.session.scalars(stmt)).all())

    async def upsert(self, node: ModelNode) -> ModelNode:
        """Insert, or update the existing node with the same (project, kind, name).

        Makes re-ingestion idempotent: a second ingest of the same node updates
        its attributes + source_sha in place rather than creating a duplicate.
        """
        existing = await self.get_by_key(node.project_id, node.kind, node.name)
        if existing is None:
            return await self.add(node)
        existing.attributes = node.attributes
        existing.source_sha = node.source_sha
        await self.session.flush()
        return existing
