"""FrontendCrawler — learn a target app's frontend at RUNTIME (stack-agnostic).

Drives the running app in a browser (via an injected PageFetcher) and reads the
rendered DOM + intercepted network — no per-stack source parsing, no framework
assumptions (Blade/Livewire/React/Vue all look the same once rendered). A bounded
BFS from a start URL (hard caps on pages/depth/time, never leaves the target
origin) produces page snapshots, which are written to the Brain as:

- ``page`` nodes (url/identity, title, forms, key elements);
- page → page ``navigates`` edges (observed links);
- page → endpoint ``calls`` edges wherever an intercepted API call matches an
  existing endpoint node — the cross-layer bridge, observed not parsed.

All writes are idempotent project-scoped upserts tagged with source_sha +
content_sha (ADR-0010 / T2.6): a re-crawl updates in place and, when an embedding
provider is configured, re-embeds only pages whose content actually changed.
Repositories do the project-scoped writes (Standards §5).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.document import build_node_document, content_sha
from app.embeddings.errors import EmbeddingDimMismatch
from app.embeddings.types import EmbeddingProvider
from app.models.enums import EdgeKind, NodeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import EMBEDDING_DIM, ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository

from .errors import CrawlConfigError
from .matching import EndpointMatcher
from .types import CrawlConfig, CrawlResult, PageFetcher, PageSnapshot
from .urls import identity, normalize, resolve, same_origin

logger = logging.getLogger("app.crawler")

# A rendered <a href> is direct DOM evidence of navigation — high confidence.
_CONFIDENCE_NAV = 0.9


def _page_attributes(snapshot: PageSnapshot, page_identity: str) -> dict[str, Any]:
    """JSON-able page node attributes. Stores the origin-relative identity (not
    the absolute URL) so content_sha is stable across environments."""
    return {
        "path": page_identity,
        "title": snapshot.title,
        "forms": [asdict(form) for form in snapshot.forms],
        "elements": [asdict(element) for element in snapshot.elements],
    }


class FrontendCrawler:
    def __init__(
        self,
        fetcher: PageFetcher,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetcher = fetcher
        self._embedding = embedding_provider
        self._now = now

    def discover(self, config: CrawlConfig) -> list[PageSnapshot]:
        """Bounded BFS from the start URL → page snapshots (no DB; pure browser).

        Enforces the caps (pages, depth, time) and the origin guard. Separated
        from persistence so the crawl traversal is testable on its own.
        """
        start = normalize(resolve(config.base_url, config.start_path))
        if not same_origin(start, config.base_url):
            raise CrawlConfigError(
                f"start path {config.start_path!r} is not on the target origin "
                f"{config.base_url!r}"
            )

        deadline = self._now() + config.time_budget_s
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        seen: set[str] = set()
        snapshots: list[PageSnapshot] = []

        while queue and len(snapshots) < config.max_pages:
            if self._now() >= deadline:
                logger.warning("crawl.time_budget_exhausted", extra={"start": start})
                break
            url, depth = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            snapshot = self._fetcher.fetch(url)
            snapshots.append(snapshot)

            if depth >= config.max_depth:
                continue
            for href in snapshot.links:
                link = normalize(resolve(snapshot.url, href))
                if link not in seen and same_origin(link, config.base_url):
                    queue.append((link, depth + 1))
        return snapshots

    async def crawl(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        config: CrawlConfig,
        source_sha: str | None = None,
    ) -> CrawlResult:
        """Crawl the target and write the result into the Brain (idempotent)."""
        snapshots = self.discover(config)

        nodes = NodeRepository(session)
        edges = EdgeRepository(session)
        endpoint_nodes = await nodes.list_by_kind(project_id, NodeKind.ENDPOINT)
        matcher = EndpointMatcher(endpoint_nodes)

        # --- page nodes (idempotent upsert + content_sha cache) --------------
        pages: dict[str, ModelNode] = {}  # identity -> node
        changed: list[tuple[ModelNode, str]] = []  # (node, document) needing embed
        for snapshot in snapshots:
            page_id = identity(snapshot.url)
            attributes = _page_attributes(snapshot, page_id)
            document = build_node_document(NodeKind.PAGE, page_id, attributes)
            new_sha = content_sha(NodeKind.PAGE, page_id, attributes, document)
            node = await nodes.upsert(
                ModelNode(
                    project_id=project_id,
                    kind=NodeKind.PAGE,
                    name=page_id,
                    attributes=attributes,
                    source_sha=source_sha,
                )
            )
            cache_hit = node.content_sha == new_sha and node.embedding is not None
            node.content_sha = new_sha
            if not cache_hit:
                changed.append((node, document))
            pages[page_id] = node

        # --- page -> page (navigates) + page -> endpoint (calls) edges -------
        nav_edges = 0
        call_edges = 0
        for snapshot in snapshots:
            src = pages[identity(snapshot.url)]
            for href in snapshot.links:
                dst = pages.get(identity(resolve(snapshot.url, href)))
                if dst is None or dst.id == src.id:
                    continue  # link target not crawled, or a self-link
                await edges.upsert(
                    ModelEdge(
                        project_id=project_id,
                        src_node_id=src.id,
                        dst_node_id=dst.id,
                        kind=EdgeKind.NAVIGATES,
                        confidence=_CONFIDENCE_NAV,
                    )
                )
                nav_edges += 1
            for call in snapshot.network:
                matched = matcher.match(call)
                if matched is None:
                    continue
                endpoint, confidence = matched
                await edges.upsert(
                    ModelEdge(
                        project_id=project_id,
                        src_node_id=src.id,
                        dst_node_id=endpoint.id,
                        kind=EdgeKind.CALLS,
                        confidence=confidence,
                    )
                )
                call_edges += 1

        await self._embed_changed(changed)
        await session.flush()

        logger.info(
            "crawl.completed",
            extra={
                "project_id": str(project_id),
                "source_sha": source_sha,
                "pages": len(pages),
                "nav_edges": nav_edges,
                "call_edges": call_edges,
            },
        )
        return CrawlResult(
            pages=len(pages),
            nav_edges=nav_edges,
            call_edges=call_edges,
            visited=tuple(pages),
        )

    async def _embed_changed(self, changed: list[tuple[ModelNode, str]]) -> None:
        """Embed only the pages whose content changed (T2.6 SHA cache)."""
        if self._embedding is None or not changed:
            return
        vectors = self._embedding.embed([document for _, document in changed])
        for (node, _document), vector in zip(changed, vectors, strict=True):
            if len(vector) != EMBEDDING_DIM:
                raise EmbeddingDimMismatch(
                    f"provider returned dim {len(vector)}, "
                    f"column expects {EMBEDDING_DIM}"
                )
            node.embedding = vector
