"""Cross-layer graph queries over the Brain — UI → API → DB (T4.3).

Pure, deterministic graph logic (no AI, no browser) on the edges other layers
already wrote: page→endpoint ``calls`` (observed by the crawler),
endpoint→model/table ``reads``/``writes`` (backend ingestion), and page→page
``navigates``. Two things live here:

1. **Robust observed-call ↔ endpoint matching** (``EndpointIndex``): an observed
   URL like ``/orders/42?status=open`` matches the source-derived endpoint node
   ``GET /orders/{id}``. Dynamic path segments are matched by template and their
   concrete values extracted; the query string is IGNORED for matching but kept
   as metadata. The metadata is stored in the existing node ``attributes`` jsonb
   (``record_observed_call``) — no new column, no migration.

2. **CrossLayerResolver** — ``journey`` (a bounded forward subgraph
   page→endpoint→model/table + nav) and ``impact`` (the 1-hop blast radius of a
   node: callers, written tables, gating roles). Both bounded, deterministic, and
   project-scoped (every read is tenancy-filtered; the graph can't leak across
   projects).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EdgeKind, NodeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository

# An exact path match is stronger evidence than a parameterised-template match
# (which could over-match a sibling route). Mirrors the crawler's tiers.
CONFIDENCE_EXACT = 0.9
CONFIDENCE_TEMPLATE = 0.7

# Hard ceiling on journey size, independent of max_depth — a runaway-graph
# backstop so one query can never walk the whole Brain.
_MAX_JOURNEY_NODES = 500


class CrossLayerError(Exception):
    """Base class for cross-layer resolution failures (Standards §7)."""


class NodeNotFoundError(CrossLayerError):
    """The start node does not exist in the given project (tenancy-scoped)."""


# --- observed-call ↔ endpoint matching --------------------------------------


@dataclass(frozen=True)
class CallMatch:
    """An observed call resolved to its endpoint node + the kept metadata."""

    endpoint: ModelNode
    path_values: dict[str, str]  # {"id": "42"} from /orders/{id} vs /orders/42
    query: dict[str, str]  # parsed query — metadata only, not used for matching
    confidence: float

    def metadata(self) -> dict[str, Any]:
        """The jsonb-storable record of this observed call (no new column)."""
        return {
            "endpoint": self.endpoint.name,
            "path_values": dict(self.path_values),
            "query": dict(self.query),
        }


def _normalize_uri(uri: str) -> str:
    uri = uri.strip().lstrip("/")
    if len(uri) > 1 and uri.endswith("/"):
        uri = uri.rstrip("/")
    return uri


def _compile_template(uri: str) -> tuple[re.Pattern[str], list[str]]:
    """``api/orders/{id}`` → (regex with one capture per ``{param}``, param names)."""
    names: list[str] = []
    segments: list[str] = []
    for seg in uri.split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            names.append(seg[1:-1])
            segments.append(r"([^/]+)")
        else:
            segments.append(re.escape(seg))
    return re.compile("^" + "/".join(segments) + "$"), names


class EndpointIndex:
    """Precomputed matcher: (method, observed URL) → endpoint node + values.

    Built once from a project's endpoint nodes (each carries ``{method, uri}``).
    Deterministic: endpoints are considered in sorted-name order so a path that
    could match two templates always resolves to the same endpoint.
    """

    def __init__(self, endpoints: list[ModelNode]) -> None:
        self._exact: dict[tuple[str, str], ModelNode] = {}
        self._templates: list[tuple[str, re.Pattern[str], list[str], ModelNode]] = []
        for node in sorted(endpoints, key=lambda n: n.name):
            method = str(node.attributes.get("method", "")).upper()
            uri = _normalize_uri(str(node.attributes.get("uri", "")))
            if not method or not uri:
                continue
            if "{" in uri:
                pattern, names = _compile_template(uri)
                self._templates.append((method, pattern, names, node))
            else:
                self._exact.setdefault((method, uri), node)

    def match(self, method: str, url: str) -> CallMatch | None:
        """Resolve one observed call, or None if no endpoint matches."""
        method = method.upper()
        parts = urlsplit(url)
        path = _normalize_uri(parts.path)
        query = dict(parse_qsl(parts.query))  # kept as metadata, last-wins

        exact = self._exact.get((method, path))
        if exact is not None:
            return CallMatch(exact, {}, query, CONFIDENCE_EXACT)
        for tmpl_method, pattern, names, node in self._templates:
            if tmpl_method != method:
                continue
            matched = pattern.match(path)
            if matched is not None:
                values = {
                    name: str(value)
                    for name, value in zip(names, matched.groups(), strict=True)
                }
                return CallMatch(node, values, query, CONFIDENCE_TEMPLATE)
        return None


def record_observed_call(page: ModelNode, match: CallMatch) -> None:
    """Append an observed call's metadata to a page node's ``attributes`` jsonb.

    Idempotent (deduped) and reassigns ``attributes`` so SQLAlchemy detects the
    change. This is the "keep the query as metadata" store, using the existing
    node jsonb — no edge column, no migration.
    """
    entry = match.metadata()
    existing: list[Any] = list(page.attributes.get("observed_calls", []))
    if entry not in existing:
        existing.append(entry)
    page.attributes = {**page.attributes, "observed_calls": existing}


# --- cross-layer traversal ---------------------------------------------------


@dataclass(frozen=True)
class Subgraph:
    """A bounded cross-layer journey: the root + reachable nodes and edges."""

    root: ModelNode
    nodes: tuple[ModelNode, ...] = field(default_factory=tuple)
    edges: tuple[ModelEdge, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Impact:
    """The 1-hop blast radius of a node (everything that depends on it)."""

    node: ModelNode
    # Nodes that call/use ``node`` (incoming edges, excluding roles).
    callers: tuple[ModelNode, ...] = field(default_factory=tuple)
    # Tables/models ``node`` writes (outgoing ``writes`` edges).
    writes: tuple[ModelNode, ...] = field(default_factory=tuple)
    # Connected role nodes that gate it (either direction).
    roles: tuple[ModelNode, ...] = field(default_factory=tuple)
    edges: tuple[ModelEdge, ...] = field(default_factory=tuple)


def _node_key(node: ModelNode) -> tuple[str, str, str]:
    return (node.kind.value, node.name, str(node.id))


def _sorted_nodes(nodes: list[ModelNode]) -> tuple[ModelNode, ...]:
    return tuple(sorted(nodes, key=_node_key))


class CrossLayerResolver:
    """Traverse the cross-layer Brain graph. All reads are project-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self._nodes = NodeRepository(session)
        self._edges = EdgeRepository(session)

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        """Bounded forward subgraph from a page/endpoint (UI → API → DB).

        BFS over OUTGOING edges (page → endpoint via ``calls``, endpoint →
        model/table via ``reads``/``writes``, page → page via ``navigates``) up to
        ``max_depth`` hops and a hard node cap. Deterministic ordering.
        """
        root = await self._nodes.get(project_id, node_id)
        if root is None:
            raise NodeNotFoundError(f"node {node_id} not found in project {project_id}")

        nodes_by_id: dict[uuid.UUID, ModelNode] = {root.id: root}
        edges_by_key: dict[tuple[uuid.UUID, uuid.UUID, EdgeKind], ModelEdge] = {}
        frontier: set[uuid.UUID] = {root.id}

        for _ in range(max(max_depth, 0)):
            if not frontier or len(nodes_by_id) >= _MAX_JOURNEY_NODES:
                break
            out_edges = await self._edges.list_from(project_id, frontier)
            discovered: set[uuid.UUID] = set()
            for edge in out_edges:
                edges_by_key[(edge.src_node_id, edge.dst_node_id, edge.kind)] = edge
                if edge.dst_node_id not in nodes_by_id:
                    discovered.add(edge.dst_node_id)
            for node in await self._nodes.get_many(project_id, discovered):
                if len(nodes_by_id) >= _MAX_JOURNEY_NODES:
                    break
                nodes_by_id[node.id] = node
            frontier = {nid for nid in discovered if nid in nodes_by_id}

        return Subgraph(
            root=root,
            nodes=_sorted_nodes(list(nodes_by_id.values())),
            edges=_sorted_edges(list(edges_by_key.values()), nodes_by_id),
        )

    async def impact(self, project_id: uuid.UUID, node_id: uuid.UUID) -> Impact:
        """The 1-hop blast radius: callers (incoming), written tables, gating roles."""
        node = await self._nodes.get(project_id, node_id)
        if node is None:
            raise NodeNotFoundError(f"node {node_id} not found in project {project_id}")

        incoming = await self._edges.list_into(project_id, {node_id})
        outgoing = await self._edges.list_from(project_id, {node_id})
        neighbour_ids = {e.src_node_id for e in incoming} | {
            e.dst_node_id for e in outgoing
        }
        neighbours = {
            n.id: n for n in await self._nodes.get_many(project_id, neighbour_ids)
        }

        roles = [n for n in neighbours.values() if n.kind is NodeKind.ROLE]
        callers = [
            neighbours[e.src_node_id]
            for e in incoming
            if e.src_node_id in neighbours
            and neighbours[e.src_node_id].kind is not NodeKind.ROLE
        ]
        writes = [
            neighbours[e.dst_node_id]
            for e in outgoing
            if e.kind is EdgeKind.WRITES and e.dst_node_id in neighbours
        ]
        return Impact(
            node=node,
            callers=_sorted_nodes(_dedup(callers)),
            writes=_sorted_nodes(_dedup(writes)),
            roles=_sorted_nodes(_dedup(roles)),
            edges=_sorted_edges(incoming + outgoing, {node.id: node, **neighbours}),
        )


def _dedup(nodes: list[ModelNode]) -> list[ModelNode]:
    seen: set[uuid.UUID] = set()
    out: list[ModelNode] = []
    for node in nodes:
        if node.id not in seen:
            seen.add(node.id)
            out.append(node)
    return out


def _sorted_edges(
    edges: list[ModelEdge], nodes_by_id: dict[uuid.UUID, ModelNode]
) -> tuple[ModelEdge, ...]:
    def _name(node_id: uuid.UUID) -> str:
        node = nodes_by_id.get(node_id)
        return node.name if node is not None else str(node_id)

    def _key(edge: ModelEdge) -> tuple[str, str, str]:
        return (_name(edge.src_node_id), _name(edge.dst_node_id), edge.kind.value)

    return tuple(sorted(edges, key=_key))
