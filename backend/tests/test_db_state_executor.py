"""Tier-aware DB-state execution (B10, ADR-0043).

Off refuses everything; read-only reads but refuses writes; full permits writes only
through the non-prod safety gate. ``tie_to_table_node`` completes the blast path.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_state.errors import ProdTargetRefused, WriteNotPermitted
from app.db_state.executor import DbStateExecutor
from app.db_state.gate import DisposableTarget
from app.db_state.oracle import TablePredicate, TableStateCheck
from app.db_state.tiers import DbStateTier
from app.models.enums import NodeKind
from app.repositories.node_repository import NodeRepository
from tests.factories import make_node, make_project

_LOCAL = DisposableTarget("postgresql+psycopg://u:p@localhost/app_dbstate", True)
_PROD = DisposableTarget("postgresql+psycopg://u:p@prod-host/app", True)


def test_off_tier_refuses_reads_and_writes() -> None:
    executor = DbStateExecutor(tier=DbStateTier.OFF)
    with pytest.raises(WriteNotPermitted, match="off"):
        executor.ensure_readable()
    with pytest.raises(WriteNotPermitted):
        executor.ensure_writable()


def test_read_only_tier_reads_but_rejects_writes() -> None:
    executor = DbStateExecutor(tier=DbStateTier.READ_ONLY, target=_LOCAL)
    executor.ensure_readable()  # permitted
    with pytest.raises(WriteNotPermitted, match="does not permit writes"):
        executor.ensure_writable()  # the read-only-rejects-writes rule


def test_full_tier_write_requires_the_safety_gate() -> None:
    # full + an explicitly-disposable, non-prod target → permitted.
    DbStateExecutor(tier=DbStateTier.FULL, target=_LOCAL).ensure_writable()
    # full + a prod-looking target → refused by the gate (never softened).
    with pytest.raises(ProdTargetRefused):
        DbStateExecutor(tier=DbStateTier.FULL, target=_PROD).ensure_writable()
    # full + no configured target → refused.
    with pytest.raises(WriteNotPermitted, match="requires a configured disposable"):
        DbStateExecutor(tier=DbStateTier.FULL).ensure_writable()


async def test_tie_to_table_node_completes_the_blast_path(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    node = await NodeRepository(db_session).add(
        make_node(
            project.id,
            kind=NodeKind.TABLE,
            name="orders",
            attributes={"table": "orders"},
        )
    )

    executor = DbStateExecutor(tier=DbStateTier.READ_ONLY)
    check = TableStateCheck("orders", TablePredicate.ROW_PRESENT, {"id": 1})
    tied = await executor.tie_to_table_node(db_session, project.id, check)
    assert tied.table_node_id == node.id  # page→endpoint→model→TABLE verified

    # Degrade: a table with no Brain node → the link is simply absent, no crash.
    untied = await executor.tie_to_table_node(
        db_session,
        project.id,
        TableStateCheck("ghost_table", TablePredicate.ROW_PRESENT, {}),
    )
    assert untied.table_node_id is None
