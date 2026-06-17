"""Repository for ``model_nodes`` (TRD §3, §7) — project-scoped, idempotent."""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, cast, select

from app.models.enums import NodeKind
from app.models.model_node import EMBEDDING_DIM, ModelNode

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

    async def search_by_vector(
        self, project_id: uuid.UUID, embedding: list[float], k: int = 5
    ) -> list[ModelNode]:
        """Top-k embedded nodes nearest the query vector (cosine), project-scoped.

        Uses the pgvector ``<=>`` cosine-distance operator, served by the HNSW
        index (migration 0005). Nodes without an embedding are excluded.
        """
        query_vec = cast(list(embedding), Vector(EMBEDDING_DIM))
        stmt = (
            select(ModelNode)
            .where(
                ModelNode.project_id == project_id,
                ModelNode.embedding.is_not(None),
            )
            .order_by(ModelNode.embedding.op("<=>")(query_vec))
            .limit(k)
        )
        return list((await self.session.scalars(stmt)).all())

    async def search_by_vector_scored(
        self, project_id: uuid.UUID, embedding: list[float], k: int = 5
    ) -> list[tuple[ModelNode, float]]:
        """Like ``search_by_vector`` but also returns cosine distance (0=identical)."""
        query_vec = cast(list(embedding), Vector(EMBEDDING_DIM))
        # return_type=Float: <=> yields a scalar distance, not a vector — without
        # this the result inherits the Vector type and pgvector mis-parses it.
        distance = (
            ModelNode.embedding.op("<=>", return_type=Float())(query_vec)
        ).label("distance")
        stmt = (
            select(ModelNode, distance)
            .where(
                ModelNode.project_id == project_id,
                ModelNode.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(k)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], float(row[1])) for row in rows]

    async def get_many(
        self, project_id: uuid.UUID, ids: set[uuid.UUID]
    ) -> list[ModelNode]:
        """Fetch nodes by id within a project (subgraph neighbour hydration)."""
        if not ids:
            return []
        stmt = select(ModelNode).where(
            ModelNode.project_id == project_id, ModelNode.id.in_(ids)
        )
        return list((await self.session.scalars(stmt)).all())
