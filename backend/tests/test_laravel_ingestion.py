"""LaravelIngester (T2.2 / ADR-0055) — whole-repo ingestion into the Brain, STATIC.

Ingestion reads the source repo only — it NEVER boots the target app (no
``artisan``, no PHP, no ``vendor/``, no DB, no config). These tests run the ingester
against the real Laravel fixture with a CommandRunner that RAISES if anything tries
to shell out, proving the static path never executes the app, and assert the produced
nodes/edges, attributes, confidence, source_sha, idempotent re-ingest, and tenancy.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.commands import CommandResult
from app.ingestion.laravel.ingester import LaravelIngester
from app.ingestion.laravel.route_list import roles_from_middleware
from app.models.enums import EdgeKind, NodeKind
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository
from tests.factories import make_project

_FIXTURE = str(Path(__file__).parent / "fixtures" / "laravel-app")
_SHA = "a" * 40


def _no_subprocess(
    argv: Sequence[str], cwd: str | None, timeout: float
) -> CommandResult:
    """Fail the test if ingestion ever shells out (proves no app boot)."""
    raise AssertionError(f"ingestion shelled out — must read source only: {list(argv)}")


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


# --- routes are static-only by default; artisan is optional, fail-safe enrichment


def test_routes_are_static_only_by_default() -> None:
    # The default path never shells out: the raising runner would fire on any call.
    facts = LaravelIngester(runner=_no_subprocess)._route_facts(_FIXTURE)
    assert {(f.method, f.uri) for f in facts} == {("POST", "users")}


def test_artisan_enrichment_merges_dynamic_routes_when_enabled() -> None:
    # With enrichment ON and the app booting, artisan-only (dynamic/package) routes
    # are merged into the static baseline, de-duplicated by (method, uri).
    artisan = json.dumps(
        [
            {  # duplicate of the static route — must NOT be added twice
                "method": "POST",
                "uri": "users",
                "name": "users.store",
                "action": "App\\Http\\Controllers\\UserController@store",
                "middleware": ["web", "auth"],
            },
            {  # a package route only artisan knows about
                "method": "GET",
                "uri": "_debugbar/health",
                "name": "debugbar.health",
                "action": "Barryvdh\\Debugbar\\Controllers\\HealthController@index",
                "middleware": ["web"],
            },
        ]
    )

    def runner(argv: Sequence[str], cwd: str | None, timeout: float) -> CommandResult:
        assert "route:list" in list(argv)  # only the artisan call is expected
        return CommandResult(0, artisan, "")

    facts = LaravelIngester(runner=runner, enrich_with_artisan=True)._route_facts(
        _FIXTURE
    )
    keys = [(f.method, f.uri) for f in facts]
    assert ("POST", "users") in keys  # static baseline kept
    assert ("GET", "_debugbar/health") in keys  # dynamic route merged in
    assert keys.count(("POST", "users")) == 1  # de-duplicated, not doubled


def test_artisan_enrichment_is_failsafe_when_the_app_will_not_boot() -> None:
    # If the optional artisan call fails (app can't boot — no DB / config / vendor),
    # enrichment is silently skipped and the static baseline stands. Ingestion is
    # NEVER blocked by a failed boot.
    def boom(argv: Sequence[str], cwd: str | None, timeout: float) -> CommandResult:
        raise RuntimeError("app failed to boot — database unreachable")

    facts = LaravelIngester(runner=boom, enrich_with_artisan=True)._route_facts(
        _FIXTURE
    )
    assert {(f.method, f.uri) for f in facts} == {("POST", "users")}  # static only


def test_head_sha_is_best_effort_and_never_aborts_ingestion() -> None:
    # git present → use the real HEAD.
    def git_ok(argv: Sequence[str], cwd: str | None, timeout: float) -> CommandResult:
        return CommandResult(0, "c" * 40 + "\n", "")

    assert LaravelIngester(runner=git_ok)._head_sha("/repo") == "c" * 40

    # git missing / not a repo → fall back to a static marker, never raise.
    def no_git(argv: Sequence[str], cwd: str | None, timeout: float) -> CommandResult:
        raise FileNotFoundError("git: command not found")

    assert LaravelIngester(runner=no_git)._head_sha("/repo") == "static-ingest"


async def test_ingest_builds_brain_from_static_source_without_booting(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    # The raising runner proves no subprocess (app boot) happens; source_sha bypasses
    # the optional git call so the whole ingest is pure static source reading.
    ingester = LaravelIngester(runner=_no_subprocess)

    result = await ingester.ingest(
        session=db_session, project_id=pid, repo_path=_FIXTURE, source_sha=_SHA
    )

    assert result.source_sha == _SHA
    assert result.nodes == {"endpoint": 1, "model": 2, "table": 2, "role": 0}
    assert result.edges == 7

    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)
    assert await nodes.count(pid) == 5

    user = await nodes.get_by_key(pid, NodeKind.MODEL, "App\\Models\\User")
    assert user is not None
    assert user.source_sha == _SHA
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
    assert endpoint.attributes["validation"]["fields"] == [
        "name",
        "email",
        "age",
        "country_id",
        "newsletter",
    ]
    assert endpoint.source_sha == _SHA

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

    await LaravelIngester(runner=_no_subprocess).ingest(
        session=db_session, project_id=pid, repo_path=_FIXTURE, source_sha=_SHA
    )
    assert await nodes.count(pid) == 5
    assert len(await edges.list(pid)) == 7

    new_sha = "b" * 40
    result = await LaravelIngester(runner=_no_subprocess).ingest(
        session=db_session, project_id=pid, repo_path=_FIXTURE, source_sha=new_sha
    )

    assert await nodes.count(pid) == 5  # updated in place, no duplicates
    assert len(await edges.list(pid)) == 7
    assert result.source_sha == new_sha
    user = await nodes.get_by_key(pid, NodeKind.MODEL, "App\\Models\\User")
    assert user is not None and user.source_sha == new_sha


async def test_ingest_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)

    await LaravelIngester(runner=_no_subprocess).ingest(
        session=db_session, project_id=project_a, repo_path=_FIXTURE, source_sha=_SHA
    )

    nodes = NodeRepository(db_session)
    edges = EdgeRepository(db_session)
    assert await nodes.count(project_a) == 5
    assert await nodes.count(project_b) == 0
    assert len(await edges.list(project_b)) == 0
