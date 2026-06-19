"""Cross-layer resolver — fast tests (pure graph logic, no real tooling).

Matching: observed URLs (dynamic segments + query) resolve to the right endpoint
node and extract path values / keep the query; non-matches return None.
journey(): a page→endpoint→table path returns the full UI→API→DB subgraph,
bounded by max_depth, project-scoped. impact(): a shared endpoint's blast radius
is its calling pages + written tables + gating roles; empty for an isolated node.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import (
    CrossLayerResolver,
    EndpointIndex,
    NodeNotFoundError,
    record_observed_call,
)
from app.models.enums import EdgeKind, NodeKind
from app.models.model_node import ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository
from tests.factories import make_edge, make_node, make_project


def _endpoint_node(name: str, method: str, uri: str) -> ModelNode:
    return ModelNode(
        project_id=uuid.uuid4(),
        kind=NodeKind.ENDPOINT,
        name=name,
        attributes={"method": method, "uri": uri},
    )


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _node(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: NodeKind,
    name: str,
    **attributes: object,
) -> ModelNode:
    return await NodeRepository(session).add(
        make_node(project_id, kind=kind, name=name, attributes=dict(attributes))
    )


async def _edge(
    session: AsyncSession,
    project_id: uuid.UUID,
    src: ModelNode,
    dst: ModelNode,
    kind: EdgeKind,
) -> None:
    await EdgeRepository(session).add(make_edge(project_id, src.id, dst.id, kind=kind))


# --- matching ----------------------------------------------------------------


def test_match_exact_dynamic_and_query() -> None:
    index = EndpointIndex(
        [
            _endpoint_node("GET api/orders", "GET", "api/orders"),
            _endpoint_node("GET api/orders/{id}", "GET", "api/orders/{id}"),
        ]
    )

    exact = index.match("GET", "http://t/api/orders")
    assert exact is not None
    assert exact.endpoint.name == "GET api/orders"
    assert exact.path_values == {} and exact.confidence == 0.9

    # Dynamic path segment matched; concrete value extracted; query KEPT as
    # metadata but ignored for matching.
    dyn = index.match("GET", "http://t/api/orders/42?status=open&page=2")
    assert dyn is not None
    assert dyn.endpoint.name == "GET api/orders/{id}"
    assert dyn.path_values == {"id": "42"}
    assert dyn.query == {"status": "open", "page": "2"}
    assert dyn.confidence == 0.7


def test_match_non_matches_return_none() -> None:
    index = EndpointIndex([_endpoint_node("GET api/orders", "GET", "api/orders")])
    assert index.match("POST", "http://t/api/orders") is None  # wrong method
    assert index.match("GET", "http://t/api/customers") is None  # wrong path
    assert index.match("GET", "http://t/api/orders/42") is None  # no template here


def test_match_normalizes_slashes_and_skips_invalid_endpoints() -> None:
    index = EndpointIndex(
        [
            _endpoint_node("GET api/items", "GET", "api/items/"),  # trailing slash
            _endpoint_node("bad", "GET", ""),  # no uri → skipped, not a crash
            _endpoint_node("GET api/x/{id}", "GET", "api/x/{id}"),  # template
        ]
    )
    # Trailing slashes (endpoint uri + call path) both normalize away.
    assert index.match("GET", "http://t/api/items/") is not None
    # A template endpoint with the wrong method does not match.
    assert index.match("POST", "http://t/api/x/42") is None


async def test_edge_repo_empty_id_sets_return_empty(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    repo = EdgeRepository(db_session)
    assert await repo.list_from(project_id, set()) == []
    assert await repo.list_into(project_id, set()) == []


async def test_record_observed_call_stores_metadata_in_jsonb(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    index = EndpointIndex(
        [_endpoint_node("GET api/orders/{id}", "GET", "api/orders/{id}")]
    )
    page = await _node(db_session, project_id, NodeKind.PAGE, "/orders")

    match = index.match("GET", "http://t/api/orders/42?status=open")
    assert match is not None
    record_observed_call(page, match)
    await db_session.flush()
    await db_session.refresh(page)

    assert page.attributes["observed_calls"] == [
        {
            "endpoint": "GET api/orders/{id}",
            "path_values": {"id": "42"},
            "query": {"status": "open"},
        }
    ]
    # Idempotent — recording the same call again does not duplicate it.
    record_observed_call(page, match)
    assert len(page.attributes["observed_calls"]) == 1


# --- journey -----------------------------------------------------------------


async def test_journey_returns_full_ui_api_db_path(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    page = await _node(db_session, project_id, NodeKind.PAGE, "/orders")
    about = await _node(db_session, project_id, NodeKind.PAGE, "/about")
    endpoint = await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "POST api/orders",
        method="POST",
        uri="api/orders",
    )
    table = await _node(db_session, project_id, NodeKind.TABLE, "orders")
    await _edge(db_session, project_id, page, endpoint, EdgeKind.CALLS)
    await _edge(db_session, project_id, endpoint, table, EdgeKind.WRITES)
    await _edge(db_session, project_id, page, about, EdgeKind.NAVIGATES)

    resolver = CrossLayerResolver(db_session)
    journey = await resolver.journey(project_id, page.id, max_depth=3)

    assert journey.root.id == page.id
    assert {n.name for n in journey.nodes} == {
        "/orders",
        "POST api/orders",
        "orders",
        "/about",
    }
    assert {e.kind for e in journey.edges} == {
        EdgeKind.CALLS,
        EdgeKind.WRITES,
        EdgeKind.NAVIGATES,
    }


async def test_journey_is_bounded_by_max_depth(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    page = await _node(db_session, project_id, NodeKind.PAGE, "/orders")
    endpoint = await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "GET api/orders",
        method="GET",
        uri="api/orders",
    )
    table = await _node(db_session, project_id, NodeKind.TABLE, "orders")
    await _edge(db_session, project_id, page, endpoint, EdgeKind.CALLS)
    await _edge(db_session, project_id, endpoint, table, EdgeKind.WRITES)

    resolver = CrossLayerResolver(db_session)
    shallow = await resolver.journey(project_id, page.id, max_depth=1)
    names = {n.name for n in shallow.nodes}
    assert "GET api/orders" in names  # 1 hop
    assert "orders" not in names  # 2 hops — beyond the bound


async def test_journey_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    page_a = await _node(db_session, project_a, NodeKind.PAGE, "/x")
    endpoint_a = await _node(
        db_session, project_a, NodeKind.ENDPOINT, "GET api/x", method="GET", uri="api/x"
    )
    await _edge(db_session, project_a, page_a, endpoint_a, EdgeKind.CALLS)
    page_b = await _node(db_session, project_b, NodeKind.PAGE, "/x")

    resolver = CrossLayerResolver(db_session)
    journey = await resolver.journey(project_a, page_a.id)
    assert all(n.project_id == project_a for n in journey.nodes)
    # B's node is invisible under A's project (tenancy), not a silent empty result.
    with pytest.raises(NodeNotFoundError):
        await resolver.journey(project_a, page_b.id)


# --- impact ------------------------------------------------------------------


async def test_impact_returns_callers_writes_and_roles(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    p1 = await _node(db_session, project_id, NodeKind.PAGE, "/orders")
    p2 = await _node(db_session, project_id, NodeKind.PAGE, "/admin/orders")
    endpoint = await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "POST api/orders",
        method="POST",
        uri="api/orders",
    )
    table = await _node(db_session, project_id, NodeKind.TABLE, "orders")
    role = await _node(db_session, project_id, NodeKind.ROLE, "admin")
    await _edge(db_session, project_id, p1, endpoint, EdgeKind.CALLS)
    await _edge(db_session, project_id, p2, endpoint, EdgeKind.CALLS)
    await _edge(db_session, project_id, endpoint, table, EdgeKind.WRITES)
    # A role connected to the endpoint (the resolver is edge-kind-agnostic for roles).
    await _edge(db_session, project_id, role, endpoint, EdgeKind.COVERS)

    impact = await CrossLayerResolver(db_session).impact(project_id, endpoint.id)

    assert {n.name for n in impact.callers} == {"/orders", "/admin/orders"}
    assert {n.name for n in impact.writes} == {"orders"}
    assert {n.name for n in impact.roles} == {"admin"}


async def test_impact_of_isolated_node_is_empty(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    endpoint = await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "GET api/lonely",
        method="GET",
        uri="api/lonely",
    )
    impact = await CrossLayerResolver(db_session).impact(project_id, endpoint.id)
    assert impact.callers == () and impact.writes == () and impact.roles == ()


async def test_impact_missing_node_raises(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    with pytest.raises(NodeNotFoundError):
        await CrossLayerResolver(db_session).impact(project_id, uuid.uuid4())
