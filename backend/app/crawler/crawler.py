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

import base64
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.strategy import NoAuthStrategy
from app.auth.types import AuthStrategy
from app.embeddings.document import build_node_document, content_sha
from app.embeddings.errors import EmbeddingDimMismatch
from app.embeddings.types import EmbeddingProvider
from app.models.enums import EdgeKind, NodeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import EMBEDDING_DIM, ModelNode
from app.progress import PHASE_CRAWL, STATUS_PASSED, emit
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository
from app.screenshots.storage import store_project_screenshot

from .errors import CrawlConfigError
from .matching import EndpointMatcher
from .types import CrawlConfig, CrawlResult, PageFetcher, PageSnapshot
from .urls import identity, normalize, resolve, same_origin

logger = logging.getLogger("app.crawler")

# A rendered <a href> is direct DOM evidence of navigation — high confidence.
_CONFIDENCE_NAV = 0.9


def _store_page_screenshot(project_id: uuid.UUID, b64: str | None) -> str | None:
    """Persist a page's screenshot under the project's folder; return the ref.

    Best-effort (ADR-0051): no screenshot, bad base64, or a storage failure returns
    None and is logged — a screenshot must NEVER break a crawl/run.
    """
    if not b64:
        return None
    try:
        return store_project_screenshot(project_id, base64.b64decode(b64))
    except Exception:  # noqa: BLE001 — a screenshot failure must not break the crawl
        logger.warning(
            "crawl.screenshot_store_failed", extra={"project_id": str(project_id)}
        )
        return None


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
        auth_strategy: AuthStrategy | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetcher = fetcher
        # One auth path: login is delegated to an AuthStrategy (default: none).
        self._auth = auth_strategy if auth_strategy is not None else NoAuthStrategy()
        self._embedding = embedding_provider
        self._now = now

    def discover(
        self, config: CrawlConfig, *, storage_state: dict[str, Any] | None = None
    ) -> list[PageSnapshot]:
        """Bounded BFS from the start URL → page snapshots (no DB; pure browser).

        Enforces the caps (pages, depth, time) and the origin guard. Each page is
        fetched with the logged-in ``storage_state`` (None → unauthenticated).
        Separated from persistence so the crawl traversal is testable on its own.
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

            snapshot = self._fetcher.fetch(url, storage_state=storage_state)
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
        """Crawl the target and write the result into the Brain (idempotent).

        Logs in once via the AuthStrategy (the tester enters OTP at most once),
        then crawls every page with that reusable session.
        """
        auth_session = await self._auth.login(
            session=session, project_id=project_id, config=config.auth
        )
        snapshots = self.discover(config, storage_state=auth_session.storage_state)

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
            # Cache key is the page's CONTENT — computed before the (random) screenshot
            # ref is attached, so a fresh screenshot each crawl never busts the cache.
            new_sha = content_sha(NodeKind.PAGE, page_id, attributes, document)
            node_attributes = dict(attributes)
            ref = _store_page_screenshot(project_id, snapshot.screenshot_b64)
            if ref is not None:
                node_attributes["screenshot_ref"] = ref
            node = await nodes.upsert(
                ModelNode(
                    project_id=project_id,
                    kind=NodeKind.PAGE,
                    name=page_id,
                    attributes=node_attributes,
                    source_sha=source_sha,
                )
            )
            cache_hit = node.content_sha == new_sha and node.embedding is not None
            node.content_sha = new_sha
            if not cache_hit:
                changed.append((node, document))
            pages[page_id] = node

            # Live "browser frame" (ADR-0050): each visited page is a watchable step
            # carrying its screenshot, so the operator sees the crawl page-by-page in
            # the live view. Best-effort no-op off the run path (no emitter installed).
            await emit(
                phase=PHASE_CRAWL,
                step=f"Visited {page_id}",
                status=STATUS_PASSED,
                detail={
                    "url": snapshot.url,
                    "title": snapshot.title,
                    "forms": len(snapshot.forms),
                    "links": len(snapshot.links),
                    "calls": len(snapshot.network),
                },
                screenshot_ref=ref,
            )

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
