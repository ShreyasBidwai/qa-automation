"""DB-state run phase (B11, ADR-0044) — tier-gated, gate-enforced, finding-emitting.

Hermetic: a fake connector yields the test session (with a real ``orders`` table in
the rolled-back transaction), a fake resolver supplies the blast-path subgraph. Pins
that off emits nothing, read_only/full emit a finding when the row is missing, the
finding is tagged + tied to the table node, and a prod target is refused without
raising.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import Subgraph
from app.db_state.run_phase import DbStateRunPhase
from app.db_state.tiers import DbStateTier
from app.models.enums import EdgeKind, FindingLayer, NodeKind, OracleSource, Outcome
from app.models.model_node import ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.finding_repository import FindingRepository
from app.repositories.node_repository import NodeRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import (
    make_edge,
    make_node,
    make_project,
    make_result,
    make_run,
    make_test_case,
)

_LOCAL = "postgresql+psycopg://u:p@localhost/app_dbstate"
_PROD = "postgresql+psycopg://u:p@prod-host/app"


class _FakeConnector:
    """Yields the test session as the assertion connection (a real orders table)."""

    def __init__(self, conn: AsyncSession) -> None:
        self._conn = conn
        self.read_only_requested: bool | None = None

    @asynccontextmanager
    async def connect(self, *, read_only: bool) -> AsyncIterator[AsyncSession]:
        self.read_only_requested = read_only
        yield self._conn


class _FakeResolver:
    """A journey subgraph endpoint→table so the finding location carries the table."""

    def __init__(self, endpoint: ModelNode, table: ModelNode) -> None:
        self._nodes = (endpoint, table)

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        return Subgraph(root=self._nodes[0], nodes=self._nodes, edges=())


async def _seed(
    session: AsyncSession,
    *,
    tier: str,
    method: str = "POST",
    columns: list[str] | None = None,
    rows: int = 0,
):  # type: ignore[no-untyped-def]
    project = make_project(db_state_tier=tier)
    session.add(project)
    await session.flush()
    nodes = NodeRepository(session)
    endpoint = await nodes.add(
        make_node(
            project.id,
            kind=NodeKind.ENDPOINT,
            name=f"{method} api/orders",
            attributes={"method": method},
        )
    )
    table = await nodes.add(
        make_node(
            project.id,
            kind=NodeKind.TABLE,
            name="orders",
            attributes={"table": "orders", "columns": columns or ["id", "status"]},
        )
    )
    await EdgeRepository(session).add(
        make_edge(project.id, endpoint.id, table.id, kind=EdgeKind.WRITES)
    )
    # The disposable target's orders table, with `rows` rows seeded.
    await session.execute(
        text(
            "CREATE TABLE orders ("
            "id integer PRIMARY KEY, status text, deleted_at timestamptz)"
        )
    )
    for i in range(rows):
        await session.execute(
            text("INSERT INTO orders (id, status) VALUES (:i, 'paid')"), {"i": i + 1}
        )
    # One run result to anchor DB-state findings to.
    run = await RunRepository(session).add(make_run(project.id))
    case = await TestCaseRepository(session).add(make_test_case(project.id))
    result = await ResultRepository(session).add(
        make_result(project.id, run.id, case.id, outcome=Outcome.PASS)
    )
    phase = DbStateRunPhase(
        session,
        resolver=_FakeResolver(endpoint, table),
        connector=_FakeConnector(session),
    )
    return project, run, table, result, phase


async def test_off_tier_emits_nothing(db_session: AsyncSession) -> None:
    project, run, _, result, phase = await _seed(db_session, tier="off")
    report = await phase.run(
        project_id=project.id,
        run_id=run.id,
        target_env_db_url=_LOCAL,
        target_db_ephemeral=True,
        results=[result],
    )
    assert report.tier is DbStateTier.OFF
    assert report.emitted_finding_ids == () and report.checks_run == 0
    assert await FindingRepository(db_session).list_for_run(project.id, run.id) == []


async def test_read_only_emits_select_finding_tagged_and_tied(
    db_session: AsyncSession,
) -> None:
    # Empty orders table → ROW_PRESENT fails → a DB-state finding.
    project, run, table, result, phase = await _seed(
        db_session, tier="read_only", rows=0
    )
    report = await phase.run(
        project_id=project.id,
        run_id=run.id,
        target_env_db_url=_LOCAL,
        target_db_ephemeral=True,
        results=[result],
    )
    assert phase._connector.read_only_requested is True  # type: ignore[attr-defined]
    assert report.checks_run == 1 and len(report.emitted_finding_ids) == 1

    findings = await FindingRepository(db_session).list_for_run(project.id, run.id)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.layer is FindingLayer.DB
    # Baseline write-landed check → characterization (pins behaviour, honestly).
    assert finding.oracle_source is OracleSource.CHARACTERIZATION
    assert finding.result_id == result.id  # anchored to a run result
    assert "orders" in finding.location["tables"]  # tied to the table node end
    assert finding.root_cause_key == "db_state:orders:row_present#characterization"


async def test_present_row_yields_no_finding(db_session: AsyncSession) -> None:
    # A row is present → ROW_PRESENT passes → no DB-state finding.
    project, run, _, result, phase = await _seed(db_session, tier="read_only", rows=1)
    report = await phase.run(
        project_id=project.id,
        run_id=run.id,
        target_env_db_url=_LOCAL,
        target_db_ephemeral=True,
        results=[result],
    )
    assert report.checks_run == 1 and report.emitted_finding_ids == ()


async def test_delete_endpoint_with_soft_delete_is_rule_derived(
    db_session: AsyncSession,
) -> None:
    # DELETE on a table with deleted_at → SOFT_DELETED rule, rule-derived. Empty
    # table → the soft-delete assertion fails → finding tagged rule-derived.
    project, run, _, result, phase = await _seed(
        db_session, tier="read_only", method="DELETE", columns=["id", "deleted_at"]
    )
    await phase.run(
        project_id=project.id,
        run_id=run.id,
        target_env_db_url=_LOCAL,
        target_db_ephemeral=True,
        results=[result],
    )
    finding = (await FindingRepository(db_session).list_for_run(project.id, run.id))[0]
    assert finding.oracle_source is OracleSource.RULE_DERIVED
    assert finding.root_cause_key == "db_state:orders:soft_deleted#rule-derived"


async def test_full_tier_against_disposable_emits(db_session: AsyncSession) -> None:
    project, run, _, result, phase = await _seed(db_session, tier="full", rows=0)
    report = await phase.run(
        project_id=project.id,
        run_id=run.id,
        target_env_db_url=_LOCAL,  # local + ephemeral → passes the gate
        target_db_ephemeral=True,
        results=[result],
    )
    assert not report.refused and len(report.emitted_finding_ids) == 1
    assert phase._connector.read_only_requested is False  # type: ignore[attr-defined]


async def test_full_tier_against_prod_target_is_refused_no_findings(
    db_session: AsyncSession,
) -> None:
    project, run, _, result, phase = await _seed(db_session, tier="full", rows=0)
    report = await phase.run(
        project_id=project.id,
        run_id=run.id,
        target_env_db_url=_PROD,  # prod host → the gate refuses
        target_db_ephemeral=True,
        results=[result],
    )
    assert report.refused and report.reason and "production" in report.reason
    assert report.emitted_finding_ids == ()
    # Refused before connecting — no findings, and (the point) no exception raised.
    assert await FindingRepository(db_session).list_for_run(project.id, run.id) == []
