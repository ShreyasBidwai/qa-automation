"""Brain schema (T2.1) — nodes/edges CRUD, tenancy, integrity, idempotent upsert."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EdgeKind, NodeKind
from app.repositories.edge_repository import EdgeRepository
from app.repositories.errors import EdgeIntegrityError
from app.repositories.node_repository import NodeRepository
from tests.factories import make_edge, make_node, make_project


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def test_node_crud(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    repo = NodeRepository(db_session)

    node = await repo.add(
        make_node(pid, kind=NodeKind.ENDPOINT, name="POST /users", source_sha="abc")
    )
    assert node.id is not None

    fetched = await repo.get(pid, node.id)
    assert fetched is not None and fetched.name == "POST /users"
    assert fetched.source_sha == "abc"

    assert [n.id for n in await repo.list(pid)] == [node.id]
    assert await repo.delete(pid, node.id) is True
    assert await repo.count(pid) == 0


async def test_edge_crud(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)

    src = await nodes.add(make_node(pid, name="ctrl"))
    dst = await nodes.add(make_node(pid, kind=NodeKind.TABLE, name="users"))

    edge = await edges.add(
        make_edge(pid, src.id, dst.id, kind=EdgeKind.WRITES, confidence=0.9)
    )
    fetched = await edges.get(pid, edge.id)
    assert fetched is not None
    assert fetched.kind is EdgeKind.WRITES
    assert fetched.confidence == pytest.approx(0.9)
    assert [e.id for e in await edges.list(pid)] == [edge.id]


async def test_tenancy_isolation(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)

    a_src = await nodes.add(make_node(project_a, name="a-ctrl"))
    a_dst = await nodes.add(make_node(project_a, kind=NodeKind.TABLE, name="a-tbl"))
    await edges.add(make_edge(project_a, a_src.id, a_dst.id))

    b_src = await nodes.add(make_node(project_b, name="b-ctrl"))
    b_dst = await nodes.add(make_node(project_b, kind=NodeKind.TABLE, name="b-tbl"))
    await edges.add(make_edge(project_b, b_src.id, b_dst.id))

    # Project A never sees project B's nodes/edges.
    a_node_ids = {n.id for n in await nodes.list(project_a)}
    assert a_node_ids == {a_src.id, a_dst.id}
    assert b_src.id not in a_node_ids
    a_edge_ids = {e.id for e in await edges.list(project_a)}
    assert len(a_edge_ids) == 1
    # Fetching B's node through project A's scope returns nothing.
    assert await nodes.get(project_a, b_src.id) is None


async def test_edge_rejects_nonexistent_node_via_repo(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    edges = EdgeRepository(db_session)
    ghost = uuid.uuid4()
    with pytest.raises(EdgeIntegrityError):
        await edges.add(make_edge(pid, ghost, ghost))


async def test_edge_rejects_cross_project_endpoints(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)

    a_node = await nodes.add(make_node(project_a, name="a"))
    b_node = await nodes.add(make_node(project_b, name="b"))

    # An edge in project A that points at a project-B node is rejected even
    # though the node row exists (the FK alone would allow it).
    with pytest.raises(EdgeIntegrityError):
        await edges.add(make_edge(project_a, a_node.id, b_node.id))


async def test_edge_fk_enforced_at_db_when_bypassing_repo(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    # Insert directly (bypassing the repo's tenancy guard) → the DB FK rejects a
    # reference to a non-existent node. A savepoint keeps the outer test
    # transaction usable after the expected failure.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(make_edge(pid, uuid.uuid4(), uuid.uuid4()))
            await db_session.flush()


async def test_node_upsert_is_idempotent(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    repo = NodeRepository(db_session)

    first = await repo.upsert(
        make_node(
            pid,
            kind=NodeKind.ENDPOINT,
            name="POST /users",
            attributes={"auth": True},
            source_sha="sha-1",
        )
    )
    second = await repo.upsert(
        make_node(
            pid,
            kind=NodeKind.ENDPOINT,
            name="POST /users",
            attributes={"auth": False},
            source_sha="sha-2",
        )
    )

    # Same key → same row updated in place, not duplicated.
    assert second.id == first.id
    assert second.attributes == {"auth": False}
    assert second.source_sha == "sha-2"
    assert await repo.count(pid) == 1


async def test_edge_upsert_is_idempotent(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)
    src = await nodes.add(make_node(pid, name="ctrl"))
    dst = await nodes.add(make_node(pid, kind=NodeKind.TABLE, name="users"))

    first = await edges.upsert(
        make_edge(pid, src.id, dst.id, kind=EdgeKind.WRITES, confidence=0.5)
    )
    second = await edges.upsert(
        make_edge(pid, src.id, dst.id, kind=EdgeKind.WRITES, confidence=0.95)
    )
    assert second.id == first.id
    assert second.confidence == pytest.approx(0.95)
    assert len(await edges.list(pid)) == 1


async def test_invalid_node_kind_rejected_by_enum(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO model_nodes (project_id, kind, name) "
                    "VALUES (:pid, 'bogus', 'x')"
                ),
                {"pid": str(pid)},
            )
