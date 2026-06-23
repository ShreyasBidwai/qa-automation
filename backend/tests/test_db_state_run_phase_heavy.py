"""DB-state run phase against a REAL disposable DB (B11, ADR-0044) — heavy lane.

Provisions a throwaway Postgres database (B10 provision path), then runs the phase
with the production ``EngineTargetConnector`` against it: an empty orders table makes
the derived ROW_PRESENT check fail, and the phase emits a layer=db finding into the
control-plane DB. Exercises the real connector + real provisioning end to end.

Run via ``make test-db-state``.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import Subgraph
from app.db_state.provision import DisposableDatabase
from app.db_state.run_phase import DbStateRunPhase, EngineTargetConnector
from app.models.enums import EdgeKind, FindingLayer, NodeKind, Outcome
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

pytestmark = pytest.mark.db_state


class _Resolver:
    def __init__(self, *nodes: ModelNode) -> None:
        self._nodes = nodes

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        return Subgraph(root=self._nodes[0], nodes=self._nodes, edges=())


def _admin_url() -> str:
    return (
        make_url(os.environ["DATABASE_URL"])
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )


async def test_full_phase_emits_finding_against_real_disposable_db(
    db_session: AsyncSession,
) -> None:
    # Control-plane Brain: a full-tier project, an endpoint that writes orders.
    project = make_project(db_state_tier="full")
    db_session.add(project)
    await db_session.flush()
    nodes = NodeRepository(db_session)
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
    await EdgeRepository(db_session).add(
        make_edge(project.id, endpoint.id, table.id, kind=EdgeKind.WRITES)
    )
    run = await RunRepository(db_session).add(make_run(project.id))
    case = await TestCaseRepository(db_session).add(make_test_case(project.id))
    result = await ResultRepository(db_session).add(
        make_result(project.id, run.id, case.id, outcome=Outcome.PASS)
    )

    # A real disposable Postgres DB with an EMPTY orders table.
    name = f"polaris_dbstate_phase_{uuid.uuid4().hex[:8]}"
    disposable = DisposableDatabase(
        admin_url=_admin_url(),
        db_name=name,
        migrations_sql=["CREATE TABLE orders (id integer PRIMARY KEY)"],
    )
    target = await disposable.provision()
    try:
        phase = DbStateRunPhase(
            db_session,
            resolver=_Resolver(endpoint, table),
            connector=EngineTargetConnector(target.url),
        )
        report = await phase.run(
            project_id=project.id,
            run_id=run.id,
            target_env_db_url=target.url,
            target_db_ephemeral=True,
            results=[result],
        )
    finally:
        await disposable.drop()

    assert not report.refused and len(report.emitted_finding_ids) == 1
    findings = await FindingRepository(db_session).list_for_run(project.id, run.id)
    finding = next(f for f in findings if f.layer is FindingLayer.DB)
    assert "orders" in finding.location["tables"]
    assert finding.root_cause_key == "db_state:orders:row_present#characterization"
