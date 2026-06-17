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
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.commands import CommandRunner, check_output, run_subprocess
from app.models.enums import EdgeKind, NodeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository

from .graph import ActionMeta, extract_graph
from .route_list import RouteFacts, all_route_facts, roles_from_middleware

logger = logging.getLogger("app.ingestion.laravel")

_GRAPH_HELPER = str(Path(__file__).parent / "php" / "extract_graph.php")

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
        graph_helper: str = _GRAPH_HELPER,
    ) -> None:
        self._runner = runner
        self._php = php_path
        self._git = git_path
        self._route_timeout = route_timeout
        self._php_timeout = php_timeout
        self._graph_helper = graph_helper

    def _head_sha(self, repo_path: str) -> str:
        result = self._runner(
            [self._git, "-C", repo_path, "rev-parse", "HEAD"],
            None,
            self._route_timeout,
        )
        return check_output(result, what="git rev-parse HEAD").strip()

    def _route_facts(self, repo_path: str) -> list[RouteFacts]:
        result = self._runner(
            [self._php, "artisan", "route:list", "--json"],
            repo_path,
            self._route_timeout,
        )
        return all_route_facts(check_output(result, what="artisan route:list"))

    async def ingest(
        self, *, session: AsyncSession, project_id: uuid.UUID, repo_path: str
    ) -> IngestResult:
        source_sha = self._head_sha(repo_path)
        facts = self._route_facts(repo_path)
        graph = extract_graph(
            repo_path=repo_path,
            runner=self._runner,
            php_path=self._php,
            helper_script=self._graph_helper,
            timeout=self._php_timeout,
        )

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
