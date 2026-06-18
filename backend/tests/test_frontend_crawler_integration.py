"""Runner integration (real browser) — FrontendCrawler against the fixture page.

Marked ``e2e_runner``: runs ONLY in the runners/playwright image via
`make test-e2e-runner`, never in the fast suite. Serves the bundled fixture page
in-process and crawls it with the REAL Playwright driver: asserts a page node is
created and that the page's intercepted ``fetch('/api/ping')`` is bridged to a
matching endpoint node as a page→endpoint ``calls`` edge — the observed
cross-layer link. The crawl driver opens/closes its own browser per page, so
nothing leaks.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.crawler import FrontendCrawler
from app.crawler.playwright_fetcher import PlaywrightPageFetcher
from app.crawler.types import CrawlConfig
from app.models.enums import EdgeKind, NodeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import ModelNode
from app.repositories.node_repository import NodeRepository
from tests.factories import make_project

pytestmark = pytest.mark.e2e_runner

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "playwright-app"


class _QuietHandler(SimpleHTTPRequestHandler):
    # Matches the base signature; silences per-request stderr logging.
    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def fixture_url() -> Iterator[str]:
    handler = partial(_QuietHandler, directory=str(_FIXTURE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_crawler_builds_page_and_observed_endpoint_edge(
    fixture_url: str, db_session: AsyncSession
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    project_id = project.id

    # The endpoint the fixture page calls (fetch('/api/ping')).
    nodes = NodeRepository(db_session)
    ping = await nodes.upsert(
        ModelNode(
            project_id=project_id,
            kind=NodeKind.ENDPOINT,
            name="GET api/ping",
            attributes={"method": "GET", "uri": "api/ping"},
            source_sha="seed",
        )
    )

    # node_project_dir defaults to "." → the image workdir (/work), which holds
    # node_modules + crawl_page.mjs.
    fetcher = PlaywrightPageFetcher(base_url=fixture_url)
    crawler = FrontendCrawler(fetcher)
    result = await crawler.crawl(
        session=db_session,
        project_id=project_id,
        config=CrawlConfig(base_url=fixture_url, max_pages=5, max_depth=1),
        source_sha="fixture-deploy",
    )

    # A page node was created for the crawled page (identity "/").
    assert result.pages >= 1
    page_nodes = await nodes.list_by_kind(project_id, NodeKind.PAGE)
    home = next(n for n in page_nodes if n.name == "/")
    assert home.source_sha == "fixture-deploy"
    # The form was extracted from the rendered DOM (stack-agnostic).
    assert any(
        field["name"] == "email"
        for form in home.attributes["forms"]
        for field in form["fields"]
    )

    # The observed page -> endpoint bridge: home --calls--> GET /api/ping.
    call_edges = list(
        await db_session.scalars(
            select(ModelEdge).where(
                ModelEdge.project_id == project_id,
                ModelEdge.kind == EdgeKind.CALLS,
            )
        )
    )
    assert any(
        e.src_node_id == home.id and e.dst_node_id == ping.id for e in call_edges
    ), "expected an observed page->endpoint edge from the intercepted fetch"
    assert result.call_edges >= 1
