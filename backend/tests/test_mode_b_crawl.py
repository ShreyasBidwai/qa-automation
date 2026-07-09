"""Frontend crawl phase at the ModeBOrchestrator seam (T4.2).

A single autonomous mode_b run now ALSO crawls the target frontend — so one run
covers backend (generate + execute) + DB-state + frontend. The crawl runs only when
a crawler is wired AND the project has a ``base_url`` to crawl; otherwise it is
skipped (crawler untouched, ``report.crawl`` is None) and the run is unaffected.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.types import AuthConfig
from app.crawler.types import CrawlConfig, CrawlResult
from app.execution.types import DbHandle, DbRole, TargetEnv
from app.models.enums import NodeKind, Outcome
from app.modes.mode_b import ModeBBounds, ModeBOrchestrator, ModeBRunReport
from app.modes.selection import FullSweepStrategy
from app.repositories.node_repository import NodeRepository
from tests.factories import make_node, make_project
from tests.test_mode_b import _FakeResolver, _StubGenerator, _StubRunner


def _env(base_url: str | None) -> TargetEnv:
    return TargetEnv(
        app_path="/u",
        execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, True),
        evidence_dir="/tmp/x",
        base_url=base_url,
    )


class _FakeCrawler:
    """Records the base_url + auth config it was driven against; returns a fixed crawl
    result (no real browser — this seam test proves the phase RUNS + how it's
    configured, not the crawl itself)."""

    def __init__(self) -> None:
        self.crawled_base: str | None = None
        self.crawled_auth: AuthConfig | None = None

    async def crawl(
        self, *, session: AsyncSession, project_id: uuid.UUID, config: CrawlConfig
    ) -> CrawlResult:
        self.crawled_base = config.base_url
        self.crawled_auth = config.auth
        return CrawlResult(pages=3, nav_edges=2, call_edges=1, visited=("/", "/a"))


class _WritingCrawler:
    """Writes a page node into the Brain during the crawl (like the real crawler), so a
    test can prove the crawl runs BEFORE target selection (ADR-0075) — the page it
    discovers is selected + tested in the SAME run, not the next one."""

    async def crawl(
        self, *, session: AsyncSession, project_id: uuid.UUID, config: CrawlConfig
    ) -> CrawlResult:
        await NodeRepository(session).add(
            make_node(project_id, kind=NodeKind.PAGE, name="/dashboard")
        )
        await session.flush()
        return CrawlResult(pages=1, nav_edges=0, call_edges=0, visited=("/dashboard",))


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    await NodeRepository(session).add(
        make_node(
            project.id,
            kind=NodeKind.ENDPOINT,
            name="POST api/orders",
            attributes={"method": "POST"},
        )
    )
    return project.id


def _orchestrator(
    session: AsyncSession,
    env: TargetEnv,
    crawler: _FakeCrawler,
    *,
    auth_config: AuthConfig | None = None,
) -> ModeBOrchestrator:
    return ModeBOrchestrator(
        session=session,
        runner=_StubRunner(outcome=Outcome.PASS),
        target_env=env,
        resolver=_FakeResolver(),
        generator=_StubGenerator(session),
        crawler=crawler,  # type: ignore[arg-type]
        auth_config=auth_config,
    )


async def _run(
    session: AsyncSession, orchestrator: ModeBOrchestrator, project_id: uuid.UUID
) -> ModeBRunReport:
    return await orchestrator.run(
        project_id=project_id,
        strategy=FullSweepStrategy(session),
        bounds=ModeBBounds(max_targets=10),
    )


async def test_crawl_phase_runs_in_a_mode_b_run(db_session: AsyncSession) -> None:
    # ONE run covers backend (executed) + the frontend crawl: the crawler is driven
    # against the project's base_url and its result rides on the unified run report.
    project_id = await _project(db_session)
    crawler = _FakeCrawler()
    report = await _run(
        db_session,
        _orchestrator(db_session, _env("http://app.local"), crawler),
        project_id,
    )
    assert crawler.crawled_base == "http://app.local"
    assert report.crawl is not None
    assert report.crawl.pages == 3 and report.crawl.nav_edges == 2


async def test_crawl_phase_skipped_without_a_frontend_url(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    crawler = _FakeCrawler()
    report = await _run(
        db_session, _orchestrator(db_session, _env(None), crawler), project_id
    )
    assert crawler.crawled_base is None  # never driven — no frontend to crawl
    assert report.crawl is None


async def test_crawl_phase_threads_the_auth_config_for_a_gated_crawl(
    db_session: AsyncSession,
) -> None:
    # With a login config wired, the crawl is driven WITH it (so it logs in + reaches
    # behind-the-gate pages); without one it crawls unauthenticated.
    auth = AuthConfig(
        login_url="https://app.local/login",
        username="runner@acme.test",
        password="pw",
        account="runner@acme.test",
    )
    project_id = await _project(db_session)
    crawler = _FakeCrawler()
    await _run(
        db_session,
        _orchestrator(db_session, _env("http://app.local"), crawler, auth_config=auth),
        project_id,
    )
    assert crawler.crawled_auth is auth  # the login config reached the crawl

    project_id2 = await _project(db_session)
    crawler2 = _FakeCrawler()
    await _run(
        db_session,
        _orchestrator(db_session, _env("http://app.local"), crawler2),
        project_id2,
    )
    assert crawler2.crawled_auth is None  # default: unauthenticated crawl


async def test_crawl_runs_before_selection_so_its_pages_are_tested_same_run(
    db_session: AsyncSession,
) -> None:
    # ADR-0075: the crawl runs FIRST, so a page it discovers joins the endpoint as a
    # SELECTED target in THIS run (previously the crawl ran last → next-run only).
    project_id = await _project(db_session)  # 1 endpoint in the Brain
    orch = _orchestrator(
        db_session,
        _env("http://app.local"),
        _WritingCrawler(),  # type: ignore[arg-type]
    )
    report = await _run(db_session, orch, project_id)

    assert report.crawl is not None and report.crawl.pages == 1
    # The endpoint + the crawl-discovered page were BOTH selected + tested this run.
    assert report.targets_selected == 2
