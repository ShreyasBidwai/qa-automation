"""DB-state phase at the ModeBOrchestrator seam (B11, ADR-0044).

The most important test here is the safety seam: a run on a project whose target
FAILS the non-prod gate has its DB-state portion REFUSED without failing the rest of
the run. Plus: off emits no DB-state finding (run unchanged), and a gate-passing run
lands a layer=db finding in the findings list, tied to the table node.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_state.run_phase import DbStateRunPhase, TargetConnector
from app.db_state.tiers import DbStateTier
from app.execution.types import DbHandle, DbRole, TargetEnv
from app.models.enums import EdgeKind, FindingLayer, NodeKind, Outcome
from app.models.finding import Finding
from app.modes.mode_b import ModeBBounds, ModeBOrchestrator, ModeBRunReport
from app.modes.selection import FullSweepStrategy
from app.repositories.edge_repository import EdgeRepository
from app.repositories.finding_repository import FindingRepository
from app.repositories.node_repository import NodeRepository
from tests.factories import make_edge, make_node, make_project
from tests.test_mode_b import _FakeResolver, _StubGenerator, _StubRunner

_LOCAL_ENV = TargetEnv(
    app_path="/u",
    execution_db=DbHandle(
        "postgresql+psycopg://u:p@localhost/app_dbstate", DbRole.WRITABLE_TEST, True
    ),
    evidence_dir="/tmp/x",
)
_PROD_ENV = TargetEnv(
    app_path="/u",
    execution_db=DbHandle(
        "postgresql+psycopg://u:p@prod-host/app", DbRole.WRITABLE_TEST, True
    ),
    evidence_dir="/tmp/x",
)


class _SessionConnector:
    """Yields the test session (a real orders table) as the assertion connection."""

    def __init__(self, conn: AsyncSession) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connect(self, *, read_only: bool) -> AsyncIterator[AsyncSession]:
        yield self._conn


class _RaisingConnector:
    """Fails loudly if reached — proves off/refused runs never connect to a DB."""

    @asynccontextmanager
    async def connect(self, *, read_only: bool) -> AsyncIterator[AsyncSession]:
        raise AssertionError("connector must not be reached for an off/refused run")
        yield  # pragma: no cover


async def _seed_brain(session: AsyncSession, *, tier: str) -> uuid.UUID:
    project = make_project(db_state_tier=tier)
    session.add(project)
    await session.flush()
    nodes = NodeRepository(session)
    endpoint = await nodes.add(
        make_node(
            project.id,
            kind=NodeKind.ENDPOINT,
            name="POST api/orders",
            attributes={"method": "POST"},
        )
    )
    table = await nodes.add(
        make_node(
            project.id,
            kind=NodeKind.TABLE,
            name="orders",
            attributes={"table": "orders", "columns": ["id"]},
        )
    )
    await EdgeRepository(session).add(
        make_edge(project.id, endpoint.id, table.id, kind=EdgeKind.WRITES)
    )
    return project.id


def _orchestrator(
    session: AsyncSession, env: TargetEnv, connector: TargetConnector
) -> ModeBOrchestrator:
    resolver = _FakeResolver()
    return ModeBOrchestrator(
        session=session,
        runner=_StubRunner(outcome=Outcome.FAIL),
        target_env=env,
        resolver=resolver,
        generator=_StubGenerator(session),
        db_state=DbStateRunPhase(session, resolver=resolver, connector=connector),
    )


async def _run(
    session: AsyncSession, orchestrator: ModeBOrchestrator, project_id: uuid.UUID
) -> ModeBRunReport:
    return await orchestrator.run(
        project_id=project_id,
        strategy=FullSweepStrategy(session),
        bounds=ModeBBounds(max_targets=10),
    )


async def _findings(
    session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID
) -> list[Finding]:
    return await FindingRepository(session).list_for_run(project_id, run_id)


def _db_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.layer is FindingLayer.DB]


async def test_off_tier_run_emits_no_db_state_finding(db_session: AsyncSession) -> None:
    project_id = await _seed_brain(db_session, tier="off")
    orchestrator = _orchestrator(db_session, _LOCAL_ENV, _RaisingConnector())
    report = await _run(db_session, orchestrator, project_id)

    assert report.db_state is not None and report.db_state.tier is DbStateTier.OFF
    findings = await _findings(db_session, project_id, report.run_id)
    assert findings  # the normal (Pest-failure) findings still exist
    assert _db_findings(findings) == []  # but no DB-state finding


async def test_full_prod_target_refuses_db_state_without_crashing_run(
    db_session: AsyncSession,
) -> None:
    """THE seam safety test: a prod target refuses DB-state, the run still completes."""
    project_id = await _seed_brain(db_session, tier="full")
    orchestrator = _orchestrator(db_session, _PROD_ENV, _RaisingConnector())
    report = await _run(db_session, orchestrator, project_id)

    # The run completed normally and produced its ordinary findings...
    assert report.status in {"passed", "failed"}
    findings = await _findings(db_session, project_id, report.run_id)
    assert findings and _db_findings(findings) == []
    # ...while the DB-state portion was refused (and never connected).
    assert report.db_state is not None
    assert report.db_state.refused and "production" in (report.db_state.reason or "")


async def test_full_local_run_lands_db_state_finding_in_findings_list(
    db_session: AsyncSession,
) -> None:
    project_id = await _seed_brain(db_session, tier="full")
    # The disposable target's (empty) orders table → ROW_PRESENT fails → a finding.
    await db_session.execute(text("CREATE TABLE orders (id integer PRIMARY KEY)"))

    orchestrator = _orchestrator(db_session, _LOCAL_ENV, _SessionConnector(db_session))
    report = await _run(db_session, orchestrator, project_id)

    assert report.db_state is not None and not report.db_state.refused
    db_findings = _db_findings(await _findings(db_session, project_id, report.run_id))
    assert len(db_findings) == 1
    finding = db_findings[0]
    assert "orders" in finding.location["tables"]  # blast path complete at the table
    assert finding.root_cause_key.startswith("db_state:orders:")
