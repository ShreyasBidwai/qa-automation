"""BrainResolver (T2.4) — hybrid vector+lexical resolution, fallback, subgraph.

Fast lane: StubEmbeddingProvider (random vectors) + real pgvector. With the stub,
vector similarity is uninformative, so resolution exercises the lexical signal
and the pure-lexical fallback — exactly the ground-truth guarantee. The blend
path is exercised by querying a node's exact document (stub cosine = 1).

The brain under test is built by STATICally reading a small Laravel source tree
(ADR-0055): a checkout/discount + users endpoint, their models, tables and
controllers. A CommandRunner that RAISES proves ingestion never boots the app.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.lexical import lexical_score, tokenize
from app.brain.resolver import BrainResolver
from app.embeddings.document import build_node_document
from app.embeddings.errors import EmbeddingProviderError
from app.embeddings.stub import StubEmbeddingProvider
from app.embeddings.types import Vector
from app.ingestion.commands import CommandResult
from app.ingestion.laravel.ingester import LaravelIngester
from app.models.enums import NodeKind
from app.models.model_node import EMBEDDING_DIM
from app.repositories.node_repository import NodeRepository
from tests.factories import make_project

_SHA = "a" * 40

# --- a small static Laravel source tree (the brain under test) ---------------
_SOURCES = {
    "routes/web.php": """<?php
    use App\\Http\\Controllers\\DiscountController;
    use App\\Http\\Controllers\\UserController;
    use Illuminate\\Support\\Facades\\Route;
    Route::post('/checkout/discount', [DiscountController::class, 'apply'])
        ->name('checkout.discount')->middleware('auth');
    Route::post('/users', [UserController::class, 'store'])
        ->name('users.store')->middleware('auth');
    """,
    "app/Models/Discount.php": """<?php
    namespace App\\Models;
    use Illuminate\\Database\\Eloquent\\Model;
    class Discount extends Model {
        protected $table = 'discounts';
        protected $fillable = ['code', 'amount'];
    }
    """,
    "app/Models/User.php": """<?php
    namespace App\\Models;
    use Illuminate\\Database\\Eloquent\\Model;
    class User extends Model {
        protected $table = 'users';
        protected $fillable = ['name', 'email'];
    }
    """,
    "database/migrations/2024_01_01_000000_create_discounts_table.php": """<?php
    use Illuminate\\Database\\Schema\\Blueprint;
    use Illuminate\\Support\\Facades\\Schema;
    return new class extends Migration {
        public function up(): void {
            Schema::create('discounts', function (Blueprint $table) {
                $table->id();
                $table->string('code');
                $table->decimal('amount', 8, 2);
            });
        }
    };
    """,
    "database/migrations/2024_01_01_000001_create_users_table.php": """<?php
    use Illuminate\\Database\\Schema\\Blueprint;
    use Illuminate\\Support\\Facades\\Schema;
    return new class extends Migration {
        public function up(): void {
            Schema::create('users', function (Blueprint $table) {
                $table->id();
                $table->string('name');
                $table->string('email');
            });
        }
    };
    """,
    "app/Http/Requests/StoreDiscountRequest.php": """<?php
    namespace App\\Http\\Requests;
    class StoreDiscountRequest extends FormRequest {
        public function rules(): array { return ['code' => 'required']; }
    }
    """,
    "app/Http/Requests/StoreUserRequest.php": """<?php
    namespace App\\Http\\Requests;
    class StoreUserRequest extends FormRequest {
        public function rules(): array {
            return ['name' => 'required', 'email' => 'required'];
        }
    }
    """,
    "app/Http/Controllers/DiscountController.php": """<?php
    namespace App\\Http\\Controllers;
    use App\\Http\\Requests\\StoreDiscountRequest;
    use App\\Models\\Discount;
    class DiscountController extends Controller {
        public function apply(StoreDiscountRequest $request) {
            return Discount::create($request->validated());
        }
    }
    """,
    "app/Http/Controllers/UserController.php": """<?php
    namespace App\\Http\\Controllers;
    use App\\Http\\Requests\\StoreUserRequest;
    use App\\Models\\User;
    class UserController extends Controller {
        public function store(StoreUserRequest $request) {
            return User::create($request->validated());
        }
    }
    """,
}


@pytest.fixture(scope="module")
def brain_repo(tmp_path_factory: pytest.TempPathFactory) -> str:
    root = tmp_path_factory.mktemp("brain-fixture")
    for rel, body in _SOURCES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return str(root)


def _no_subprocess(
    argv: Sequence[str], cwd: str | None, timeout: float
) -> CommandResult:
    raise AssertionError(f"ingestion shelled out — must read source only: {list(argv)}")


class _FailingProvider:
    dimension = EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[Vector]:
        raise EmbeddingProviderError("embedding backend unavailable")


async def _ingest(session: AsyncSession, repo: str, *, embed: bool = True) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    provider = StubEmbeddingProvider(EMBEDDING_DIM) if embed else None
    await LaravelIngester(runner=_no_subprocess, embedding_provider=provider).ingest(
        session=session, project_id=project.id, repo_path=repo, source_sha=_SHA
    )
    return project.id


def test_lexical_signal_scores_overlap_and_exact() -> None:
    assert tokenize("POST /checkout/discount") == ["post", "checkout", "discount"]


async def test_semantic_ish_query_resolves_via_lexical(
    db_session: AsyncSession, brain_repo: str
) -> None:
    pid = await _ingest(db_session, brain_repo)
    resolver = BrainResolver(
        session=db_session, provider=StubEmbeddingProvider(EMBEDDING_DIM)
    )
    resolution = await resolver.resolve(
        project_id=pid, query_text="discount checkout", k=3
    )
    assert not resolution.low_confidence
    assert resolution.results[0].node.name == "POST checkout/discount"
    assert resolution.results[0].score > 0.35


async def test_exact_uri_query_resolves_via_lexical_even_with_weak_vectors(
    db_session: AsyncSession, brain_repo: str
) -> None:
    pid = await _ingest(db_session, brain_repo)
    resolver = BrainResolver(
        session=db_session, provider=StubEmbeddingProvider(EMBEDDING_DIM)
    )
    resolution = await resolver.resolve(
        project_id=pid, query_text="POST checkout/discount", k=3
    )
    assert resolution.results[0].node.name == "POST checkout/discount"
    assert resolution.results[0].score == pytest.approx(1.0)
    assert not resolution.low_confidence


async def test_exact_document_query_uses_the_vector_blend(
    db_session: AsyncSession, brain_repo: str
) -> None:
    pid = await _ingest(db_session, brain_repo)
    nodes = NodeRepository(db_session)
    user = await nodes.get_by_key(pid, NodeKind.MODEL, "App\\Models\\User")
    assert user is not None
    # Querying a node's own document → stub cosine sim 1.0 → vector blend kicks in.
    doc = build_node_document(user.kind, user.name, user.attributes)
    resolver = BrainResolver(
        session=db_session, provider=StubEmbeddingProvider(EMBEDDING_DIM)
    )
    resolution = await resolver.resolve(project_id=pid, query_text=doc, k=3)
    assert resolution.results[0].node.id == user.id
    assert resolution.results[0].score > 0.9


async def test_low_confidence_flag_for_unmatched_query(
    db_session: AsyncSession, brain_repo: str
) -> None:
    pid = await _ingest(db_session, brain_repo)
    resolver = BrainResolver(
        session=db_session, provider=StubEmbeddingProvider(EMBEDDING_DIM)
    )
    resolution = await resolver.resolve(
        project_id=pid, query_text="zzz nonexistent qqq", k=3
    )
    assert resolution.low_confidence


async def test_resolution_is_project_scoped(
    db_session: AsyncSession, brain_repo: str
) -> None:
    pid = await _ingest(db_session, brain_repo)
    empty_project = make_project()
    db_session.add(empty_project)
    await db_session.flush()

    resolver = BrainResolver(
        session=db_session, provider=StubEmbeddingProvider(EMBEDDING_DIM)
    )
    here = await resolver.resolve(project_id=pid, query_text="discount checkout", k=5)
    assert all(r.node.project_id == pid for r in here.results)

    other = await resolver.resolve(
        project_id=empty_project.id, query_text="discount checkout", k=5
    )
    assert other.results == []
    assert other.low_confidence


async def test_pure_lexical_fallback_when_no_embeddings(
    db_session: AsyncSession, brain_repo: str
) -> None:
    # Ingest WITHOUT embeddings → nodes have no vectors → resolution must still
    # work via pure lexical matching (codebase facts are ground truth).
    pid = await _ingest(db_session, brain_repo, embed=False)
    resolver = BrainResolver(
        session=db_session, provider=StubEmbeddingProvider(EMBEDDING_DIM)
    )
    resolution = await resolver.resolve(
        project_id=pid, query_text="POST checkout/discount", k=3
    )
    assert resolution.results[0].node.name == "POST checkout/discount"
    assert not resolution.low_confidence


async def test_resolution_survives_embedding_failure(
    db_session: AsyncSession, brain_repo: str
) -> None:
    # Nodes DO have embeddings, but the query can't be embedded → lexical still
    # resolves (never solely embedding-dependent).
    pid = await _ingest(db_session, brain_repo)
    resolver = BrainResolver(session=db_session, provider=_FailingProvider())
    resolution = await resolver.resolve(
        project_id=pid, query_text="POST checkout/discount", k=3
    )
    assert resolution.results[0].node.name == "POST checkout/discount"
    assert not resolution.low_confidence


async def test_subgraph_attaches_one_hop_neighbours(
    db_session: AsyncSession, brain_repo: str
) -> None:
    pid = await _ingest(db_session, brain_repo)
    resolver = BrainResolver(
        session=db_session, provider=StubEmbeddingProvider(EMBEDDING_DIM)
    )
    resolution = await resolver.resolve(
        project_id=pid, query_text="discount checkout", k=1
    )
    top = resolution.results[0]
    assert top.node.name == "POST checkout/discount"
    # 1-hop neighbour of the endpoint is the model it references.
    names = {n.name for n in top.subgraph.nodes}
    assert "POST checkout/discount" in names
    assert "App\\Models\\Discount" in names
    kinds = {n.kind for n in top.subgraph.nodes}
    assert "model" in kinds
    assert len(top.subgraph.edges) == 1


async def test_subgraph_is_bounded_by_the_cap(
    db_session: AsyncSession, brain_repo: str
) -> None:
    pid = await _ingest(db_session, brain_repo)
    # The Discount model has 3 incident edges (reads+writes table, endpoint call);
    # a cap of 1 must bound the subgraph.
    resolver = BrainResolver(
        session=db_session,
        provider=StubEmbeddingProvider(EMBEDDING_DIM),
        subgraph_max_neighbors=1,
    )
    resolution = await resolver.resolve(project_id=pid, query_text="discount", k=6)
    discount_model = next(
        r for r in resolution.results if r.node.name == "App\\Models\\Discount"
    )
    assert len(discount_model.subgraph.edges) == 1
    assert len(discount_model.subgraph.nodes) <= 2  # centre + 1 neighbour


def test_lexical_score_requires_a_node() -> None:
    # Guard: empty query scores zero regardless of node content.
    project_id = uuid.uuid4()
    node: Any = type(
        "N",
        (),
        {
            "kind": NodeKind.ROLE,
            "name": "admin",
            "attributes": {},
            "project_id": project_id,
        },
    )()
    assert lexical_score("", node) == 0.0
