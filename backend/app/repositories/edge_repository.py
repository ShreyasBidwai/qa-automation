"""Repository for ``model_edges`` (TRD §3, §7) — project-scoped, idempotent.

Enforces edge tenancy: both endpoints must be existing nodes in the edge's own
project (the FK guarantees existence; this rejects cross-project references the
FK alone would allow).
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select

from app.models.enums import EdgeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import ModelNode

from .base import ProjectScopedRepository
from .errors import EdgeIntegrityError


class EdgeRepository(ProjectScopedRepository[ModelEdge]):
    model = ModelEdge

    async def _node_in_project(self, project_id: uuid.UUID, node_id: uuid.UUID) -> bool:
        stmt = select(ModelNode.id).where(
            ModelNode.project_id == project_id, ModelNode.id == node_id
        )
        return (await self.session.scalar(stmt)) is not None

    async def _assert_endpoints(self, edge: ModelEdge) -> None:
        for label, node_id in (
            ("src", edge.src_node_id),
            ("dst", edge.dst_node_id),
        ):
            if not await self._node_in_project(edge.project_id, node_id):
                raise EdgeIntegrityError(
                    f"edge {label} node {node_id} is not a node in project "
                    f"{edge.project_id}"
                )

    async def add(self, entity: ModelEdge) -> ModelEdge:
        await self._assert_endpoints(entity)
        return await super().add(entity)

    async def list_incident(
        self, project_id: uuid.UUID, node_id: uuid.UUID, limit: int
    ) -> list[ModelEdge]:
        """Edges touching a node (as src or dst), capped — for 1-hop expansion."""
        stmt = (
            select(ModelEdge)
            .where(
                ModelEdge.project_id == project_id,
                or_(
                    ModelEdge.src_node_id == node_id,
                    ModelEdge.dst_node_id == node_id,
                ),
            )
            .order_by(ModelEdge.created_at)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_by_key(
        self,
        project_id: uuid.UUID,
        src_node_id: uuid.UUID,
        dst_node_id: uuid.UUID,
        kind: EdgeKind,
    ) -> ModelEdge | None:
        stmt = select(ModelEdge).where(
            ModelEdge.project_id == project_id,
            ModelEdge.src_node_id == src_node_id,
            ModelEdge.dst_node_id == dst_node_id,
            ModelEdge.kind == kind,
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def upsert(self, edge: ModelEdge) -> ModelEdge:
        """Insert, or update confidence on the matching (project, src, dst, kind)."""
        await self._assert_endpoints(edge)
        existing = await self.get_by_key(
            edge.project_id, edge.src_node_id, edge.dst_node_id, edge.kind
        )
        if existing is None:
            return await super().add(edge)
        existing.confidence = edge.confidence
        await self.session.flush()
        return existing
