"""LaravelIngester (T2.2) — whole-repo ingestion into the Brain, offline.

Injects a fake CommandRunner returning canned git/route:list/extract_graph
output (no live PHP) and asserts the produced nodes/edges, attributes,
confidence, source_sha, idempotent re-ingest, and tenancy.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.commands import CommandResult
from app.ingestion.laravel.ingester import LaravelIngester
from app.ingestion.laravel.route_list import roles_from_middleware
from app.models.enums import EdgeKind, NodeKind
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository
from tests.factories import make_project

_ROUTES = json.dumps(
    [
        {
            "method": "POST",
            "uri": "users",
            "name": "users.store",
            "action": "App\\Http\\Controllers\\UserController@store",
            "middleware": ["web", "auth"],
        },
        {
            "method": "GET|HEAD",
            "uri": "up",
            "name": None,
            "action": "Closure",
            "middleware": ["web"],
        },
        {
            "method": "GET|HEAD",
            "uri": "admin/reports",
            "name": "admin.reports",
            "action": "App\\Http\\Controllers\\AdminController@index",
            "middleware": ["web", "auth", "role:admin"],
        },
    ]
)

_GRAPH = json.dumps(
    {
        "models": [
            {
                "class": "App\\Models\\User",
                "table": "users",
                "fillable": ["name", "email", "age", "country_id", "newsletter"],
                "relationships": [
                    {
                        "name": "country",
                        "kind": "belongsTo",
                        "related": "App\\Models\\Country",
                    }
                ],
            },
            {
                "class": "App\\Models\\Country",
                "table": "countries",
                "fillable": ["name"],
                "relationships": [
                    {
                        "name": "users",
                        "kind": "hasMany",
                        "related": "App\\Models\\User",
                    }
                ],
            },
        ],
        "migrations": [
            {
                "table": "countries",
                "columns": ["id", "name", "created_at", "updated_at"],
            },
            {
                "table": "users",
                "columns": [
                    "id",
                    "name",
                    "email",
                    "age",
                    "country_id",
                    "newsletter",
                    "created_at",
                    "updated_at",
                ],
            },
        ],
        "actions": [
            {
                "controller": "App\\Http\\Controllers\\UserController",
                "action": "store",
                "model_refs": ["App\\Models\\User"],
                "validation": {
                    "source": "form_request",
                    "fields": ["name", "email", "age", "country_id", "newsletter"],
                },
            }
        ],
    }
)


def _runner(sha: str):
    def runner(argv: Sequence[str], cwd: str | None, timeout: float) -> CommandResult:
        args = list(argv)
        if "rev-parse" in args:
            return CommandResult(0, f"{sha}\n", "")
        if "route:list" in args:
            return CommandResult(0, _ROUTES, "")
        if any("extract_graph" in a for a in args):
            return CommandResult(0, _GRAPH, "")
        raise AssertionError(f"unexpected command in test: {args}")

    return runner


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


def test_roles_from_middleware_parses_and_dedupes() -> None:
    assert roles_from_middleware(["web", "auth"]) == []
    assert roles_from_middleware(["auth", "role:admin"]) == ["admin"]
    assert roles_from_middleware(["role:admin,editor", "role:admin"]) == [
        "admin",
        "editor",
    ]


async def test_ingest_populates_brain_with_nodes_edges_and_sha(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    sha = "a" * 40
    ingester = LaravelIngester(runner=_runner(sha))

    result = await ingester.ingest(
        session=db_session, project_id=pid, repo_path="/repo"
    )

    assert result.source_sha == sha
    assert result.nodes == {"endpoint": 3, "model": 2, "table": 2, "role": 1}
    assert result.edges == 7

    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)
    assert await nodes.count(pid) == 8

    user = await nodes.get_by_key(pid, NodeKind.MODEL, "App\\Models\\User")
    assert user is not None
    assert user.source_sha == sha
    assert user.attributes["table"] == "users"
    assert user.attributes["fillable"][0] == "name"
    assert user.attributes["relationships"][0] == {
        "name": "country",
        "kind": "belongsTo",
        "related": "App\\Models\\Country",
    }

    users_table = await nodes.get_by_key(pid, NodeKind.TABLE, "users")
    assert users_table is not None
    assert "country_id" in users_table.attributes["columns"]

    endpoint = await nodes.get_by_key(pid, NodeKind.ENDPOINT, "POST users")
    assert endpoint is not None
    assert endpoint.attributes["auth_required"] is True
    assert endpoint.attributes["action"].endswith("UserController@store")
    assert endpoint.attributes["validation"]["source"] == "form_request"
    assert endpoint.source_sha == sha

    assert await nodes.get_by_key(pid, NodeKind.ROLE, "admin") is not None

    country = await nodes.get_by_key(pid, NodeKind.MODEL, "App\\Models\\Country")
    assert country is not None
    all_edges = await edges.list(pid)

    # model -> table: reads + writes, high confidence.
    model_to_table = [
        e
        for e in all_edges
        if e.src_node_id == user.id and e.dst_node_id == users_table.id
    ]
    assert {e.kind for e in model_to_table} == {EdgeKind.READS, EdgeKind.WRITES}
    assert all(e.confidence == pytest.approx(0.9) for e in model_to_table)

    # model -> model: declared relationship, calls, high confidence.
    model_to_model = [
        e
        for e in all_edges
        if e.src_node_id == user.id
        and e.dst_node_id == country.id
        and e.kind is EdgeKind.CALLS
    ]
    assert len(model_to_model) == 1
    assert model_to_model[0].confidence == pytest.approx(0.9)

    # endpoint -> model: statically referenced, calls, medium confidence.
    endpoint_to_model = [
        e
        for e in all_edges
        if e.src_node_id == endpoint.id
        and e.dst_node_id == user.id
        and e.kind is EdgeKind.CALLS
    ]
    assert len(endpoint_to_model) == 1
    assert endpoint_to_model[0].confidence == pytest.approx(0.6)


async def test_reingest_is_idempotent_and_updates_sha_in_place(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)

    await LaravelIngester(runner=_runner("a" * 40)).ingest(
        session=db_session, project_id=pid, repo_path="/repo"
    )
    nodes_after_first = await nodes.count(pid)
    edges_after_first = len(await edges.list(pid))

    # Re-ingest the same repo at a new HEAD → updates in place, no duplicates.
    new_sha = "b" * 40
    result = await LaravelIngester(runner=_runner(new_sha)).ingest(
        session=db_session, project_id=pid, repo_path="/repo"
    )

    assert await nodes.count(pid) == nodes_after_first == 8
    assert len(await edges.list(pid)) == edges_after_first == 7
    assert result.source_sha == new_sha
    user = await nodes.get_by_key(pid, NodeKind.MODEL, "App\\Models\\User")
    assert user is not None and user.source_sha == new_sha


async def test_ingest_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)

    await LaravelIngester(runner=_runner("a" * 40)).ingest(
        session=db_session, project_id=project_a, repo_path="/repo"
    )

    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)
    assert await nodes.count(project_a) == 8
    assert await nodes.count(project_b) == 0
    assert len(await edges.list(project_b)) == 0
