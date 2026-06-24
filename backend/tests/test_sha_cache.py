"""SHA-keyed embed cache (ADR-0010, T2.6) — re-ingest re-embeds only changed nodes.

Fast lane: a StubEmbeddingProvider wrapped in a call/text counter is the cache
assertion — the provider must not be called for unchanged nodes. source_sha
(HEAD provenance) still refreshes on every re-ingest; content_sha is the cache key.

Ingestion is fully STATIC (ADR-0055): the brain is built by reading the real Laravel
fixture's source, and a CommandRunner that RAISES proves no app/subprocess boot. The
"changed node" case mutates a source file on disk, the static analogue of the old
canned-JSON change.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path

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

_FIXTURE = str(Path(__file__).parent / "fixtures" / "laravel-app")
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _no_subprocess(
    argv: Sequence[str], cwd: str | None, timeout: float
) -> CommandResult:
    """Fail the test if ingestion ever shells out (proves no app boot)."""
    raise AssertionError(f"ingestion shelled out — must read source only: {list(argv)}")


def _copy_fixture(dst: Path) -> str:
    repo = dst / "app-copy"
    shutil.copytree(_FIXTURE, repo)
    return str(repo)


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
    await LaravelIngester(runner=_no_subprocess, embedding_provider=counter).ingest(
        session=db_session, project_id=pid, repo_path=_FIXTURE, source_sha=_SHA_A
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

    await LaravelIngester(runner=_no_subprocess, embedding_provider=counter).ingest(
        session=db_session, project_id=pid, repo_path=_FIXTURE, source_sha=_SHA_A
    )
    cold_calls, cold_texts = counter.calls, counter.texts
    before = {
        n.id: (_emb(n), n.content_sha)
        for n in await NodeRepository(db_session).list(pid)
    }

    # Re-ingest identical content at a NEW HEAD commit.
    await LaravelIngester(runner=_no_subprocess, embedding_provider=counter).ingest(
        session=db_session, project_id=pid, repo_path=_FIXTURE, source_sha=_SHA_B
    )

    # The provider was not called again — zero re-embedding.
    assert counter.calls == cold_calls
    assert counter.texts == cold_texts

    for node in await NodeRepository(db_session).list(pid):
        assert node.source_sha == _SHA_B  # provenance refreshed
        prev_vec, prev_sha = before[node.id]
        assert node.content_sha == prev_sha  # cache key unchanged
        assert _emb(node) == prev_vec  # vector reused


async def test_reingest_reembeds_only_the_changed_node(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    pid = await _project(db_session)
    counter = _CountingProvider()
    repo = _copy_fixture(tmp_path)

    await LaravelIngester(runner=_no_subprocess, embedding_provider=counter).ingest(
        session=db_session, project_id=pid, repo_path=repo, source_sha=_SHA_A
    )
    cold_texts = counter.texts
    by_name = {n.name: n for n in await NodeRepository(db_session).list(pid)}
    user_before = _emb(by_name["App\\Models\\User"])
    country_before = _emb(by_name["App\\Models\\Country"])

    # Mutate ONLY the User model's source — adds a $fillable column. Its extracted
    # content changes; every other node's is byte-identical.
    user_php = Path(repo) / "app" / "Models" / "User.php"
    user_php.write_text(
        user_php.read_text().replace(
            "'newsletter',", "'newsletter',\n        'phone',"
        ),
        encoding="utf-8",
    )

    await LaravelIngester(runner=_no_subprocess, embedding_provider=counter).ingest(
        session=db_session, project_id=pid, repo_path=repo, source_sha=_SHA_B
    )

    assert counter.texts - cold_texts == 1  # exactly one node re-embedded

    after = {n.name: n for n in await NodeRepository(db_session).list(pid)}
    assert _emb(after["App\\Models\\User"]) != user_before  # re-embedded
    assert _emb(after["App\\Models\\Country"]) == country_before  # cached


async def test_cache_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    counter = _CountingProvider()

    ingester = LaravelIngester(runner=_no_subprocess, embedding_provider=counter)
    await ingester.ingest(
        session=db_session, project_id=project_a, repo_path=_FIXTURE, source_sha=_SHA_A
    )
    await ingester.ingest(
        session=db_session, project_id=project_b, repo_path=_FIXTURE, source_sha=_SHA_A
    )
    # Identical content in a DIFFERENT project is not a cache hit — embedded fresh.
    assert counter.texts == 10

    # Re-ingesting A (unchanged) is a cache hit and never touches B.
    before = counter.texts
    await LaravelIngester(runner=_no_subprocess, embedding_provider=counter).ingest(
        session=db_session, project_id=project_a, repo_path=_FIXTURE, source_sha=_SHA_B
    )
    assert counter.texts == before
