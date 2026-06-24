"""LaravelIngester — deterministic whole-repo ingestion into the Brain (T2.2).

Reuses T1.3's injectable runners (route:list + the php-parser helpers) and the
T2.1 NodeRepository/EdgeRepository idempotent upserts. No AI, no git provider —
a local repo path. Every node is tagged with the repo's HEAD commit SHA (the
cache/change-invalidation carrier, ADR-0010); re-ingesting the same repo updates
in place rather than duplicating. Edges carry confidence — only reliably
derivable relationships are emitted; the rest are skipped, not guessed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.document import build_node_document, content_sha
from app.embeddings.errors import EmbeddingDimMismatch
from app.embeddings.types import EmbeddingProvider
from app.ingestion.commands import CommandRunner, run_subprocess
from app.models.enums import EdgeKind, NodeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import EMBEDDING_DIM, ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository

from .graph import ActionMeta
from .route_list import RouteFacts, all_route_facts, roles_from_middleware
from .static_graph import parse_graph
from .static_routes import parse_routes

logger = logging.getLogger("app.ingestion.laravel")

# Confidence: high for statically certain links (ORM backing, declared
# relationships); medium for inferred ones (a controller statically naming a
# model). Anything less reliable is skipped entirely.
_CONFIDENCE_HIGH = 0.9
_CONFIDENCE_MEDIUM = 0.6


@dataclass(frozen=True)
class IngestResult:
    source_sha: str
    nodes: dict[str, int]  # node-kind value -> count
    edges: int


def _split_action(action: str) -> tuple[str, str] | None:
    """`App\\...\\UserController@store` -> (controller_fqcn, method); else None."""
    if "@" not in action:
        return None
    controller, _, method = action.partition("@")
    controller = controller.lstrip("\\")
    if not controller or not method:
        return None
    return controller, method


class LaravelIngester:
    def __init__(
        self,
        *,
        runner: CommandRunner = run_subprocess,
        php_path: str = "php",
        git_path: str = "git",
        route_timeout: float = 60.0,
        php_timeout: float = 60.0,
        embedding_provider: EmbeddingProvider | None = None,
        enrich_with_artisan: bool = False,
    ) -> None:
        self._runner = runner
        self._php = php_path
        self._git = git_path
        self._route_timeout = route_timeout
        self._php_timeout = php_timeout
        self._embedding = embedding_provider
        # OPTIONAL, OFF BY DEFAULT, FULLY FAIL-SAFE route enrichment (ADR-0055): only
        # when the target happens to boot, merge artisan-discovered (dynamic/package)
        # routes into the static set. Ingestion NEVER depends on it.
        self._enrich_with_artisan = enrich_with_artisan

    def _head_sha(self, repo_path: str) -> str:
        """The repo's HEAD commit — best-effort. Ingestion needs only the SOURCE, so a
        missing git / non-repo path falls back to a static marker rather than failing
        (ADR-0055)."""
        try:
            result = self._runner(
                [self._git, "-C", repo_path, "rev-parse", "HEAD"],
                None,
                self._route_timeout,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:  # noqa: BLE001 — git is optional; never abort ingestion
            pass
        logger.info("ingestion.laravel.head_sha_unavailable", extra={"repo": repo_path})
        return "static-ingest"

    def _route_facts(self, repo_path: str) -> list[RouteFacts]:
        """Routes from STATIC source parsing (the guaranteed baseline, no app boot).

        Optionally merges artisan route:list when ``enrich_with_artisan`` AND the app
        happens to boot — fully fail-safe: any error and the static results stand.
        """
        parsed = parse_routes(repo_path)
        if parsed.unresolved:
            logger.info(
                "ingestion.laravel.routes_unresolved",
                extra={
                    "count": len(parsed.unresolved),
                    "samples": parsed.unresolved[:5],
                },
            )
        facts = parsed.facts
        if self._enrich_with_artisan:
            facts = self._merge_artisan_routes(repo_path, facts)
        return facts

    def _merge_artisan_routes(
        self, repo_path: str, static_facts: list[RouteFacts]
    ) -> list[RouteFacts]:
        """Best-effort: add artisan-only routes (dynamic/package-registered) to the
        static set, de-duplicated. ANY failure → the static results stand."""
        try:
            result = self._runner(
                [self._php, "artisan", "route:list", "--json"],
                repo_path,
                self._route_timeout,
            )
            if result.returncode != 0:
                return static_facts
            artisan_facts = all_route_facts(result.stdout)
        except Exception:  # noqa: BLE001 — enrichment can never break ingestion
            logger.info("ingestion.laravel.artisan_enrichment_skipped")
            return static_facts
        seen = {(f.method, f.uri) for f in static_facts}
        merged = list(static_facts)
        for fact in artisan_facts:
            key = (fact.method, fact.uri)
            if key not in seen:
                seen.add(key)
                merged.append(fact)
        return merged

    async def ingest(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        repo_path: str,
        source_sha: str | None = None,
    ) -> IngestResult:
        # When a caller already resolved the commit (e.g. GitProvider.checkout),
        # use it; otherwise resolve the local repo's HEAD.
        if source_sha is None:
            source_sha = self._head_sha(repo_path)
        facts = self._route_facts(repo_path)
        # Models / migrations / controllers from STATIC source parsing — no app boot,
        # no vendor/autoload, no DB, no config (ADR-0055).
        graph = parse_graph(repo_path)

        nodes = NodeRepository(session)
        edges = EdgeRepository(session)
        action_map = {(a.controller, a.action): a for a in graph.actions}

        # --- nodes (all tagged with source_sha; idempotent upsert) -----------
        table_nodes: dict[str, ModelNode] = {}
        for migration in graph.migrations:
            table_nodes[migration.table] = await nodes.upsert(
                ModelNode(
                    project_id=project_id,
                    kind=NodeKind.TABLE,
                    name=migration.table,
                    attributes={"table": migration.table, "columns": migration.columns},
                    source_sha=source_sha,
                )
            )

        model_nodes: dict[str, ModelNode] = {}
        for model in graph.models:
            model_nodes[model.cls] = await nodes.upsert(
                ModelNode(
                    project_id=project_id,
                    kind=NodeKind.MODEL,
                    name=model.cls,
                    attributes={
                        "class": model.cls,
                        "table": model.table,
                        "fillable": model.fillable,
                        "relationships": [asdict(r) for r in model.relationships],
                    },
                    source_sha=source_sha,
                )
            )

        endpoint_nodes: list[ModelNode] = []
        endpoint_actions: list[tuple[ModelNode, ActionMeta]] = []
        for fact in facts:
            split = _split_action(fact.action)
            action_meta = action_map.get(split) if split else None
            validation = (
                asdict(action_meta.validation)
                if action_meta
                else {"source": "none", "fields": []}
            )
            endpoint = await nodes.upsert(
                ModelNode(
                    project_id=project_id,
                    kind=NodeKind.ENDPOINT,
                    name=f"{fact.method} {fact.uri}",
                    attributes={
                        "method": fact.method,
                        "uri": fact.uri,
                        "name": fact.name,
                        "auth_required": fact.auth_required,
                        "action": fact.action,
                        "middleware": fact.middleware,
                        "validation": validation,
                    },
                    source_sha=source_sha,
                )
            )
            endpoint_nodes.append(endpoint)
            if action_meta is not None:
                endpoint_actions.append((endpoint, action_meta))

        role_nodes: dict[str, ModelNode] = {}
        for fact in facts:
            for role in roles_from_middleware(fact.middleware):
                if role not in role_nodes:
                    role_nodes[role] = await nodes.upsert(
                        ModelNode(
                            project_id=project_id,
                            kind=NodeKind.ROLE,
                            name=role,
                            attributes={"role": role},
                            source_sha=source_sha,
                        )
                    )

        # --- edges (nodes now exist → FK + tenancy satisfied) ----------------
        edge_count = 0

        async def _edge(
            src: uuid.UUID, dst: uuid.UUID, kind: EdgeKind, confidence: float
        ) -> None:
            nonlocal edge_count
            await edges.upsert(
                ModelEdge(
                    project_id=project_id,
                    src_node_id=src,
                    dst_node_id=dst,
                    kind=kind,
                    confidence=confidence,
                )
            )
            edge_count += 1

        # model -> table (ORM backing): reads + writes, high confidence.
        for model in graph.models:
            src = model_nodes.get(model.cls)
            table = table_nodes.get(model.table)
            if src is None or table is None:
                continue
            await _edge(src.id, table.id, EdgeKind.READS, _CONFIDENCE_HIGH)
            await _edge(src.id, table.id, EdgeKind.WRITES, _CONFIDENCE_HIGH)

        # model -> model (declared relationship), high confidence.
        for model in graph.models:
            src = model_nodes.get(model.cls)
            if src is None:
                continue
            for relationship in model.relationships:
                dst = model_nodes.get(relationship.related)
                if dst is None:  # related class isn't a known model → skip
                    continue
                await _edge(src.id, dst.id, EdgeKind.CALLS, _CONFIDENCE_HIGH)

        # endpoint -> model (controller statically references a model), medium.
        for endpoint, action_meta in endpoint_actions:
            for ref in action_meta.model_refs:
                dst = model_nodes.get(ref)
                if dst is None:
                    continue
                await _edge(endpoint.id, dst.id, EdgeKind.CALLS, _CONFIDENCE_MEDIUM)

        # --- embed nodes, SHA-cached (ADR-0010 / T2.6) -----------------------
        # content_sha is a hash of each node's EXTRACTED content. A node is
        # re-embedded only when its content_sha is new or changed; an unchanged
        # node reuses its stored vector (its source_sha provenance was already
        # refreshed by the upsert). The provider is NOT called for unchanged
        # nodes, turning re-ingest from O(all nodes) into O(changed nodes).
        # (Reconciling DELETED nodes — sources that disappeared on re-ingest — is
        # a separate follow-up, out of scope here.)
        if self._embedding is not None:
            all_nodes = [
                *table_nodes.values(),
                *model_nodes.values(),
                *endpoint_nodes,
                *role_nodes.values(),
            ]
            changed: list[tuple[ModelNode, str]] = []
            for node in all_nodes:
                document = build_node_document(node.kind, node.name, node.attributes)
                new_sha = content_sha(node.kind, node.name, node.attributes, document)
                if node.content_sha == new_sha and node.embedding is not None:
                    continue  # cache hit: reuse vector, content unchanged
                node.content_sha = new_sha
                changed.append((node, document))

            if changed:  # never call the provider when nothing changed
                vectors = self._embedding.embed([doc for _, doc in changed])
                for (node, _document), vector in zip(changed, vectors, strict=True):
                    if len(vector) != EMBEDDING_DIM:
                        raise EmbeddingDimMismatch(
                            f"provider returned dim {len(vector)}, "
                            f"column expects {EMBEDDING_DIM}"
                        )
                    node.embedding = vector
            await session.flush()

        node_counts = {
            NodeKind.ENDPOINT.value: sum(1 for _ in facts),
            NodeKind.MODEL.value: len(model_nodes),
            NodeKind.TABLE.value: len(table_nodes),
            NodeKind.ROLE.value: len(role_nodes),
        }
        logger.info(
            "ingestion.laravel.repo_ingested",
            extra={"source_sha": source_sha, "nodes": node_counts, "edges": edge_count},
        )
        return IngestResult(source_sha=source_sha, nodes=node_counts, edges=edge_count)
