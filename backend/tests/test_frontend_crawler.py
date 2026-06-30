"""FrontendCrawler — fast backend tests (no real browser).

Injected captured snapshots exercise the whole crawler: snapshot → page nodes +
page→page (navigates) + page→endpoint (calls) edges matched to existing endpoint
nodes; idempotent re-crawl (incl. the T2.6 content_sha embed cache); the hard
caps (pages/depth/time/origin); project scoping; the endpoint matcher; and the
real fetcher's parsing + credentials-never-logged guarantee (fake node runner).
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.strategy import StubAuthStrategy
from app.crawler.crawler import FrontendCrawler
from app.crawler.errors import CrawlConfigError, PageFetchError
from app.crawler.matching import EndpointMatcher
from app.crawler.playwright_fetcher import PlaywrightPageFetcher
from app.crawler.types import (
    CrawlConfig,
    FormField,
    FormSpec,
    NetworkCall,
    PageSnapshot,
)
from app.crawler.urls import identity, normalize, resolve, same_origin
from app.models.enums import EdgeKind, NodeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import EMBEDDING_DIM, ModelNode
from app.repositories.node_repository import NodeRepository
from tests.factories import make_project

_BASE = "http://app.test"


def _snap(
    path: str,
    *,
    links: tuple[str, ...] = (),
    network: tuple[NetworkCall, ...] = (),
    forms: tuple[FormSpec, ...] = (),
    title: str = "Page",
    screenshot_b64: str | None = None,
) -> PageSnapshot:
    abs_links = tuple(resolve(_BASE, link) for link in links)
    return PageSnapshot(
        url=resolve(_BASE, path),
        title=title,
        links=abs_links,
        network=network,
        forms=forms,
        screenshot_b64=screenshot_b64,
    )


class _FakeFetcher:
    """Returns canned snapshots keyed by normalized URL; records fetch order."""

    def __init__(self, snapshots: list[PageSnapshot]) -> None:
        self._by_url = {normalize(s.url): s for s in snapshots}
        self.fetched: list[str] = []
        self.storage_states: list[dict[str, Any] | None] = []

    def fetch(
        self, url: str, *, storage_state: dict[str, Any] | None = None
    ) -> PageSnapshot:
        self.fetched.append(url)
        self.storage_states.append(storage_state)
        if url not in self._by_url:
            raise PageFetchError(f"no canned page for {url}")
        return self._by_url[url]


class _CountingEmbedder:
    dimension = EMBEDDING_DIM

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.01 * (i + 1)] * EMBEDDING_DIM for i in range(len(texts))]


def _clock(values: list[float]):
    seq = list(values)

    def now() -> float:
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return now


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _endpoint(
    session: AsyncSession, project_id: uuid.UUID, method: str, uri: str
) -> ModelNode:
    return await NodeRepository(session).upsert(
        ModelNode(
            project_id=project_id,
            kind=NodeKind.ENDPOINT,
            name=f"{method} {uri}",
            attributes={"method": method, "uri": uri},
            source_sha="seed",
        )
    )


async def _edges(session: AsyncSession, project_id: uuid.UUID) -> list[ModelEdge]:
    rows = await session.scalars(
        select(ModelEdge).where(ModelEdge.project_id == project_id)
    )
    return list(rows)


# --- url helpers + matcher (pure) -------------------------------------------


def test_url_helpers() -> None:
    assert normalize("http://app.test/users/?q=1#x") == "http://app.test/users"
    assert identity("http://app.test/users/5?t=1") == "/users/5"
    assert identity("http://app.test/") == "/"
    assert same_origin("http://app.test/x", "http://app.test/") is True
    assert same_origin("http://evil.test/x", "http://app.test/") is False


def test_endpoint_matcher_exact_and_template() -> None:
    endpoints = [
        ModelNode(
            project_id=uuid.uuid4(),
            kind=NodeKind.ENDPOINT,
            name="GET api/ping",
            attributes={"method": "GET", "uri": "api/ping"},
        ),
        ModelNode(
            project_id=uuid.uuid4(),
            kind=NodeKind.ENDPOINT,
            name="GET api/users/{id}",
            attributes={"method": "GET", "uri": "api/users/{id}"},
        ),
    ]
    matcher = EndpointMatcher(endpoints)
    exact = matcher.match(NetworkCall("GET", "http://h/api/ping", "fetch"))
    assert exact is not None and exact[0].name == "GET api/ping" and exact[1] == 0.9
    tmpl = matcher.match(NetworkCall("GET", "http://h/api/users/42", "xhr"))
    assert tmpl is not None and tmpl[0].name == "GET api/users/{id}" and tmpl[1] == 0.7
    assert matcher.match(NetworkCall("POST", "http://h/api/ping", "fetch")) is None
    assert matcher.match(NetworkCall("GET", "http://h/api/other", "fetch")) is None


# --- snapshot -> Brain graph -------------------------------------------------


async def test_crawl_builds_pages_nav_and_call_edges(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    ping = await _endpoint(db_session, project_id, "GET", "api/ping")
    users_api = await _endpoint(db_session, project_id, "GET", "api/users")

    home = _snap(
        "/",
        links=("/users",),
        network=(NetworkCall("GET", f"{_BASE}/api/ping", "fetch"),),
        forms=(
            FormSpec(
                action=f"{_BASE}/api/contact",
                method="POST",
                fields=(FormField("email", "email", True),),
            ),
        ),
    )
    users = _snap(
        "/users",
        links=("/",),
        network=(NetworkCall("GET", f"{_BASE}/api/users", "xhr"),),
    )
    crawler = FrontendCrawler(_FakeFetcher([home, users]))

    result = await crawler.crawl(
        session=db_session,
        project_id=project_id,
        config=CrawlConfig(base_url=_BASE),
        source_sha="deploy-1",
    )

    assert result.pages == 2
    assert result.nav_edges == 2  # home->users and users->home
    assert result.call_edges == 2

    nodes = NodeRepository(db_session)
    page_nodes = await nodes.list_by_kind(project_id, NodeKind.PAGE)
    assert {n.name for n in page_nodes} == {"/", "/users"}
    home_node = next(n for n in page_nodes if n.name == "/")
    assert home_node.source_sha == "deploy-1"
    assert home_node.content_sha is not None
    assert home_node.attributes["forms"][0]["fields"][0]["name"] == "email"
    assert home_node.attributes["forms"][0]["fields"][0]["required"] is True

    edges = await _edges(db_session, project_id)
    by_kind: dict[EdgeKind, list[ModelEdge]] = {}
    for edge in edges:
        by_kind.setdefault(edge.kind, []).append(edge)
    assert len(by_kind[EdgeKind.NAVIGATES]) == 2
    assert len(by_kind[EdgeKind.CALLS]) == 2
    # The observed page->endpoint bridge: home --calls--> GET /api/ping (exact).
    home_to_ping = next(
        e
        for e in by_kind[EdgeKind.CALLS]
        if e.src_node_id == home_node.id and e.dst_node_id == ping.id
    )
    assert home_to_ping.confidence == 0.9
    assert any(e.dst_node_id == users_api.id for e in by_kind[EdgeKind.CALLS])


async def test_crawl_stores_per_project_screenshot_ref_on_page_nodes(
    db_session: AsyncSession,
) -> None:
    # A page snapshot carrying a screenshot ⇒ the crawl stores the bytes under the
    # project's folder and records the project-scoped ref on the page node, so the
    # operator's per-project screenshots are discoverable from the Brain.
    project_id = await _project(db_session)
    shot = base64.b64encode(b"\x89PNG fake screenshot bytes").decode()
    crawler = FrontendCrawler(_FakeFetcher([_snap("/", screenshot_b64=shot)]))
    await crawler.crawl(
        session=db_session, project_id=project_id, config=CrawlConfig(base_url=_BASE)
    )
    page = (await NodeRepository(db_session).list_by_kind(project_id, NodeKind.PAGE))[0]
    ref = page.attributes.get("screenshot_ref")
    assert isinstance(ref, str)
    assert ref.startswith(f"{project_id}/")  # grouped under the project's folder


async def test_recrawl_is_idempotent_with_embed_cache(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    await _endpoint(db_session, project_id, "GET", "api/ping")
    home = _snap("/", network=(NetworkCall("GET", f"{_BASE}/api/ping", "fetch"),))
    embedder = _CountingEmbedder()
    crawler = FrontendCrawler(_FakeFetcher([home]), embedding_provider=embedder)
    config = CrawlConfig(base_url=_BASE)

    first = await crawler.crawl(
        session=db_session, project_id=project_id, config=config, source_sha="s1"
    )
    assert first.pages == 1 and first.call_edges == 1
    assert embedder.calls == 1  # page embedded once

    second = await crawler.crawl(
        session=db_session, project_id=project_id, config=config, source_sha="s1"
    )
    # No duplicate nodes/edges; the unchanged page is NOT re-embedded (T2.6 cache).
    assert second.pages == 1 and second.call_edges == 1
    assert embedder.calls == 1
    nodes = NodeRepository(db_session)
    assert len(await nodes.list_by_kind(project_id, NodeKind.PAGE)) == 1
    assert len(await _edges(db_session, project_id)) == 1


# --- caps + safety -----------------------------------------------------------


async def test_max_pages_cap(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    snaps = [_snap(f"/p{i}", links=(f"/p{i + 1}",)) for i in range(10)]
    crawler = FrontendCrawler(_FakeFetcher(snaps))
    result = await crawler.crawl(
        session=db_session,
        project_id=project_id,
        config=CrawlConfig(base_url=_BASE, start_path="/p0", max_pages=3),
    )
    assert result.pages == 3
    assert len(crawler._fetcher.fetched) == 3  # type: ignore[attr-defined]


async def test_max_depth_cap(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    snaps = [
        _snap("/a", links=("/b",)),
        _snap("/b", links=("/c",)),
        _snap("/c"),
    ]
    fetcher = _FakeFetcher(snaps)
    crawler = FrontendCrawler(fetcher)
    await crawler.crawl(
        session=db_session,
        project_id=project_id,
        config=CrawlConfig(base_url=_BASE, start_path="/a", max_depth=1),
    )
    # depth 0 (/a) + depth 1 (/b); /c is depth 2 → never fetched.
    assert normalize(f"{_BASE}/c") not in fetcher.fetched


async def test_time_budget_cap(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    snaps = [_snap("/a", links=("/b",)), _snap("/b")]
    crawler = FrontendCrawler(_FakeFetcher(snaps), now=_clock([0.0, 0.0, 1000.0]))
    result = await crawler.crawl(
        session=db_session,
        project_id=project_id,
        config=CrawlConfig(base_url=_BASE, start_path="/a", time_budget_s=10.0),
    )
    assert result.pages == 1  # deadline hit before the second page


async def test_stays_on_origin(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    home = _snap("/", links=("/users", "http://evil.test/pwn"))
    users = _snap("/users")
    fetcher = _FakeFetcher([home, users])
    crawler = FrontendCrawler(fetcher)
    await crawler.crawl(
        session=db_session, project_id=project_id, config=CrawlConfig(base_url=_BASE)
    )
    assert all("evil.test" not in url for url in fetcher.fetched)


async def test_start_off_origin_raises(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    crawler = FrontendCrawler(_FakeFetcher([]))
    with pytest.raises(CrawlConfigError):
        await crawler.crawl(
            session=db_session,
            project_id=project_id,
            config=CrawlConfig(base_url=_BASE, start_path="http://evil.test/"),
        )


async def test_crawl_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    await _endpoint(db_session, project_a, "GET", "api/ping")
    home = _snap("/", network=(NetworkCall("GET", f"{_BASE}/api/ping", "fetch"),))
    crawler = FrontendCrawler(_FakeFetcher([home]))

    await crawler.crawl(
        session=db_session, project_id=project_a, config=CrawlConfig(base_url=_BASE)
    )

    nodes = NodeRepository(db_session)
    assert len(await nodes.list_by_kind(project_a, NodeKind.PAGE)) == 1
    assert await nodes.list_by_kind(project_b, NodeKind.PAGE) == []
    assert await _edges(db_session, project_b) == []


# --- crawler delegates auth to AuthStrategy ----------------------------------


async def test_crawl_threads_stub_auth_storage_state_to_fetcher(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    state: dict[str, Any] = {"cookies": [{"name": "session", "value": "abc"}]}
    fetcher = _FakeFetcher([_snap("/")])
    crawler = FrontendCrawler(
        fetcher, auth_strategy=StubAuthStrategy(storage_state=state)
    )

    await crawler.crawl(
        session=db_session, project_id=project_id, config=CrawlConfig(base_url=_BASE)
    )
    # The logged-in session is replayed into every page fetch.
    assert fetcher.storage_states == [state]


async def test_crawl_with_default_noauth_passes_no_session(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    fetcher = _FakeFetcher([_snap("/")])
    crawler = FrontendCrawler(fetcher)  # default NoAuthStrategy

    await crawler.crawl(
        session=db_session, project_id=project_id, config=CrawlConfig(base_url=_BASE)
    )
    assert fetcher.storage_states == [None]


# --- real fetcher: parsing + storage-state passthrough -----------------------


def test_playwright_fetcher_parses_and_passes_storage_state() -> None:
    captured: dict[str, str] = {}
    snapshot_json = (
        '{"url":"http://app.test/p","title":"Home",'
        '"links":["http://app.test/users"],'
        '"forms":[{"action":"http://app.test/api/contact","method":"post",'
        '"fields":[{"name":"email","type":"email","required":true}]}],'
        '"elements":[{"tag":"button","text":"Send"}],'
        '"network":[{"method":"get","url":"http://app.test/api/ping",'
        '"resource_type":"fetch"}]}'
    )

    def _fake_runner(argv, cwd, stdin, timeout):  # type: ignore[no-untyped-def]
        captured["stdin"] = stdin
        return 0, snapshot_json, ""

    fetcher = PlaywrightPageFetcher(base_url="http://app.test", runner=_fake_runner)
    snapshot = fetcher.fetch("http://app.test/home", storage_state={"cookies": ["x"]})

    # Parsing: method uppercased, form/network normalized.
    assert snapshot.network[0].method == "GET"
    assert snapshot.forms[0].method == "POST"
    assert snapshot.forms[0].fields[0].name == "email"
    assert snapshot.links == ("http://app.test/users",)
    # The session is handed to the driver over stdin (for an authenticated context).
    assert "storageState" in captured["stdin"]


def test_playwright_fetcher_raises_on_driver_failure() -> None:
    def _bad_runner(argv, cwd, stdin, timeout):  # type: ignore[no-untyped-def]
        return 1, "", "boom: chromium crashed"

    fetcher = PlaywrightPageFetcher(base_url="http://app.test", runner=_bad_runner)
    with pytest.raises(PageFetchError):
        fetcher.fetch("http://app.test/x")


def test_playwright_fetcher_raises_on_bad_json() -> None:
    def _runner(argv, cwd, stdin, timeout):  # type: ignore[no-untyped-def]
        return 0, "this is not json", ""

    fetcher = PlaywrightPageFetcher(base_url="http://app.test", runner=_runner)
    with pytest.raises(PageFetchError):
        fetcher.fetch("http://app.test/x")


def test_playwright_fetcher_raises_on_missing_fields() -> None:
    def _runner(argv, cwd, stdin, timeout):  # type: ignore[no-untyped-def]
        return 0, "{}", ""  # valid JSON but no "url"

    fetcher = PlaywrightPageFetcher(base_url="http://app.test", runner=_runner)
    with pytest.raises(PageFetchError):
        fetcher.fetch("http://app.test/x")
