"""SHA-keyed embed cache (ADR-0010, T2.6) — re-ingest re-embeds only changed nodes.

Fast lane: a StubEmbeddingProvider wrapped in a call/text counter is the cache
assertion — the provider must not be called for unchanged nodes. source_sha
(HEAD provenance) still refreshes on every re-ingest; content_sha is the cache key.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.document import content_sha
from app.embeddings.stub import StubEmbeddingProvider
from app.embeddings.types import Vector
from app.ingestion.commands import CommandResult
from app.ingestion.laravel.ingester import LaravelIngester
from app.models.enums import NodeKind
from app.models.model_node import EMBEDDING_DIM
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
        }
    ]
)


def _graph(user_fillable: list[str]) -> str:
    return json.dumps(
        {
            "models": [
                {
                    "class": "App\\Models\\User",
                    "table": "users",
                    "fillable": user_fillable,
                    "relationships": [],
                },
                {
                    "class": "App\\Models\\Country",
                    "table": "countries",
                    "fillable": ["name"],
                    "relationships": [],
                },
            ],
            "migrations": [
                {"table": "users", "columns": ["id", "name", "email"]},
                {"table": "countries", "columns": ["id", "name"]},
            ],
            "actions": [
                {
                    "controller": "App\\Http\\Controllers\\UserController",
                    "action": "store",
                    "model_refs": ["App\\Models\\User"],
                    "validation": {"source": "form_request", "fields": ["name"]},
                }
            ],
        }
    )


_GRAPH = _graph(["name", "email"])
_GRAPH_USER_CHANGED = _graph(["name", "email", "phone"])  # User content changes


def _runner(graph: str = _GRAPH, sha: str = "a" * 40):
    def runner(argv: Sequence[str], cwd: str | None, timeout: float) -> CommandResult:
        args = list(argv)
        if "rev-parse" in args:
            return CommandResult(0, f"{sha}\n", "")
        if "route:list" in args:
            return CommandResult(0, _ROUTES, "")
        if any("extract_graph" in a for a in args):
            return CommandResult(0, graph, "")
        raise AssertionError(f"unexpected command in test: {args}")

    return runner


class _CountingProvider:
    """Wraps the deterministic stub and counts embed() work (the cache assertion)."""

    def __init__(self, dimension: int = EMBEDDING_DIM) -> None:
        self.dimension = dimension
        self._stub = StubEmbeddingProvider(dimension)
        self.calls = 0
        self.texts = 0

    def embed(self, texts: list[str]) -> list[Vector]:
        self.calls += 1
        self.texts += len(texts)
        return self._stub.embed(texts)


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


def _emb(node: object) -> list[float]:
    # pgvector returns a numpy array; normalise to a list (and handle None).
    vector = getattr(node, "embedding", None)
    return [] if vector is None else [float(x) for x in vector]


def test_content_sha_is_deterministic_and_order_independent() -> None:
    base = content_sha(
        NodeKind.MODEL, "App\\Models\\User", {"table": "users", "fillable": ["n"]}, "d"
    )
    same = content_sha(
        NodeKind.MODEL, "App\\Models\\User", {"fillable": ["n"], "table": "users"}, "d"
    )
    assert base == same  # attribute order doesn't change the hash
    changed = content_sha(
        NodeKind.MODEL,
        "App\\Models\\User",
        {"table": "users", "fillable": ["n", "m"]},
        "d2",
    )
    assert changed != base  # changed extracted content → different hash


async def test_cold_ingest_embeds_all_nodes(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    counter = _CountingProvider()
    await LaravelIngester(runner=_runner(), embedding_provider=counter).ingest(
        session=db_session, project_id=pid, repo_path="/repo"
    )
    nodes = await NodeRepository(db_session).list(pid)
    assert len(nodes) == 5
    assert counter.texts == 5  # every node embedded on a cold ingest
    assert all(n.content_sha is not None and n.embedding is not None for n in nodes)


async def test_reingest_unchanged_is_a_cache_hit_but_refreshes_source_sha(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    counter = _CountingProvider()

    await LaravelIngester(
        runner=_runner(sha="a" * 40), embedding_provider=counter
    ).ingest(session=db_session, project_id=pid, repo_path="/repo")
    cold_calls, cold_texts = counter.calls, counter.texts
    before = {
        n.id: (_emb(n), n.content_sha)
        for n in await NodeRepository(db_session).list(pid)
    }

    # Re-ingest identical content at a NEW HEAD commit.
    await LaravelIngester(
        runner=_runner(sha="b" * 40), embedding_provider=counter
    ).ingest(session=db_session, project_id=pid, repo_path="/repo")

    # The provider was not called again — zero re-embedding.
    assert counter.calls == cold_calls
    assert counter.texts == cold_texts

    for node in await NodeRepository(db_session).list(pid):
        assert node.source_sha == "b" * 40  # provenance refreshed
        prev_vec, prev_sha = before[node.id]
        assert node.content_sha == prev_sha  # cache key unchanged
        assert _emb(node) == prev_vec  # vector reused


async def test_reingest_reembeds_only_the_changed_node(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    counter = _CountingProvider()

    await LaravelIngester(
        runner=_runner(_GRAPH, "a" * 40), embedding_provider=counter
    ).ingest(session=db_session, project_id=pid, repo_path="/repo")
    cold_texts = counter.texts
    by_name = {n.name: n for n in await NodeRepository(db_session).list(pid)}
    user_before = _emb(by_name["App\\Models\\User"])
    country_before = _emb(by_name["App\\Models\\Country"])

    # Re-ingest with ONLY the User model's extracted content changed.
    await LaravelIngester(
        runner=_runner(_GRAPH_USER_CHANGED, "b" * 40), embedding_provider=counter
    ).ingest(session=db_session, project_id=pid, repo_path="/repo")

    assert counter.texts - cold_texts == 1  # exactly one node re-embedded

    after = {n.name: n for n in await NodeRepository(db_session).list(pid)}
    assert _emb(after["App\\Models\\User"]) != user_before  # re-embedded
    assert _emb(after["App\\Models\\Country"]) == country_before  # cached


async def test_cache_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    counter = _CountingProvider()

    ingester = LaravelIngester(runner=_runner(), embedding_provider=counter)
    await ingester.ingest(session=db_session, project_id=project_a, repo_path="/repo")
    await ingester.ingest(session=db_session, project_id=project_b, repo_path="/repo")
    # Identical content in a DIFFERENT project is not a cache hit — embedded fresh.
    assert counter.texts == 10

    # Re-ingesting A (unchanged) is a cache hit and never touches B.
    before = counter.texts
    await LaravelIngester(
        runner=_runner(sha="b" * 40), embedding_provider=counter
    ).ingest(session=db_session, project_id=project_a, repo_path="/repo")
    assert counter.texts == before
