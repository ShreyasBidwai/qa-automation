"""DB-state run phase — wire the B10 engine into a live run (ADR-0044).

After a run executes, this phase derives DB-state checks from the Brain
(endpoint→table ``writes`` edges), runs them against the run's target database, and
emits any failures as ordinary ``Finding`` rows (``layer=db``) so they land in the
same findings pipeline as everything else — tagged with the honest oracle source
(B10) and tied to the Brain table node so the page→endpoint→model→table blast path
is verified at the table end.

The B10 safety rule still governs and is enforced HERE, at the orchestrator seam:
the ``full`` write path goes through ``DbStateExecutor.ensure_writable`` → the
prod-refusal gate before anything connects with intent to write. If the target
fails the gate, the phase REFUSES the DB-state portion and returns a report saying
why — it never raises into the run, so the rest of the run is unaffected. ``off``
(the default) skips entirely: zero behaviour change for existing projects.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.brain.cross_layer import Subgraph
from app.models.enums import EdgeKind, FindingLayer, NodeKind
from app.models.finding import SEVERITY_UNSET, STATUS_OPEN, Finding
from app.models.finding_result import FindingResult
from app.models.model_node import ModelNode
from app.models.result import Result
from app.repositories.edge_repository import EdgeRepository
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_result_repository import FindingResultRepository
from app.repositories.node_repository import NodeRepository
from app.repositories.project_repository import ProjectRepository

from .errors import DbStateError
from .executor import DbStateExecutor
from .gate import DisposableTarget
from .oracle import TablePredicate, TableStateCheck, classify_oracle
from .tiers import DbStateTier

logger = logging.getLogger("app.db_state.run_phase")


class _Resolver(Protocol):
    """The cross-layer journey the phase needs to build a location (BrainResolver)."""

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph: ...


class TargetConnector(Protocol):
    """Yields a connection to the run's target database for assertions.

    ``read_only=True`` (the read_only tier) must hand back a connection that cannot
    write. Injected, so the heavy lane uses a real disposable Postgres DB and fast
    tests use a connection to a seeded table.
    """

    def connect(
        self, *, read_only: bool
    ) -> AbstractAsyncContextManager[AsyncConnection | AsyncSession]: ...


class EngineTargetConnector:
    """The production connector: a connection to the run's target DB by URL.

    For ``read_only`` it opens a transaction set ``READ ONLY`` so even a buggy check
    cannot write; the transaction is always rolled back, so assertions never persist
    anything to the target. (Postgres-shaped; non-Postgres targets degrade via the
    orchestrator's defensive guard — DB-state must never crash a run.)
    """

    def __init__(self, url: str) -> None:
        self._url = url

    @asynccontextmanager
    async def connect(self, *, read_only: bool) -> AsyncIterator[AsyncConnection]:
        engine = create_async_engine(self._url)
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                if read_only:
                    await conn.execute(text("SET TRANSACTION READ ONLY"))
                try:
                    yield conn
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()


@dataclass(frozen=True)
class DbStateRunCheck:
    """A check to run in a run, with the endpoint that anchors its blast path."""

    check: TableStateCheck
    endpoint_node_id: uuid.UUID


@dataclass(frozen=True)
class DbStatePhaseReport:
    """What the DB-state phase did — observable for the run report + tests."""

    tier: DbStateTier
    emitted_finding_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    checks_run: int = 0
    refused: bool = False
    reason: str | None = None


def _location_from_subgraph(subgraph: Subgraph | None) -> dict[str, Any]:
    """The page→endpoint→model→table blast path, mirroring the assembler's shape."""
    if subgraph is None:
        return {}
    nodes = subgraph.nodes
    return {
        "page": next((n.name for n in nodes if n.kind is NodeKind.PAGE), None),
        "endpoints": [n.name for n in nodes if n.kind is NodeKind.ENDPOINT],
        "models": [n.name for n in nodes if n.kind is NodeKind.MODEL],
        "tables": [n.name for n in nodes if n.kind is NodeKind.TABLE],
    }


async def derive_checks(
    session: AsyncSession, project_id: uuid.UUID
) -> list[DbStateRunCheck]:
    """Deterministic DB-state checks from the Brain's endpoint→table writes.

    For each ``endpoint --writes--> table`` edge, assert the table received a row
    (``row_present``, characterization — it pins that the endpoint writes the
    table). A DELETE endpoint whose table has a ``deleted_at`` column instead
    asserts the soft-delete RULE (``soft_deleted``, rule-derived). Ordered by
    (endpoint name, table name) so a run's checks are stable.
    """
    nodes = NodeRepository(session)
    endpoints = await nodes.list_by_kind(project_id, NodeKind.ENDPOINT)
    if not endpoints:
        return []
    by_id = {n.id: n for n in endpoints}
    edges = await EdgeRepository(session).list_from(project_id, set(by_id))
    tables = {n.id: n for n in await nodes.list_by_kind(project_id, NodeKind.TABLE)}

    derived: list[tuple[str, str, DbStateRunCheck]] = []
    for edge in edges:
        if edge.kind is not EdgeKind.WRITES:
            continue
        table = tables.get(edge.dst_node_id)
        endpoint = by_id.get(edge.src_node_id)
        if table is None or endpoint is None:
            continue
        check = _check_for(endpoint, table)
        derived.append((endpoint.name, table.name, DbStateRunCheck(check, endpoint.id)))

    derived.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in derived]


def _check_for(endpoint: ModelNode, table: ModelNode) -> TableStateCheck:
    method = str((endpoint.attributes or {}).get("method", "")).upper()
    columns = {str(c) for c in (table.attributes or {}).get("columns", [])}
    if method == "DELETE" and "deleted_at" in columns:
        # The soft-delete rule: a deleted row is flagged, not gone (rule-derived).
        return TableStateCheck(
            table=table.name,
            predicate=TablePredicate.SOFT_DELETED,
            where={},
            oracle_source=classify_oracle(schema_backed=True),
        )
    # Baseline: the write should have landed a row (pins behaviour → characterization).
    return TableStateCheck(
        table=table.name,
        predicate=TablePredicate.ROW_PRESENT,
        where={},
        oracle_source=classify_oracle(schema_backed=False),
    )


class DbStateRunPhase:
    """Run DB-state checks for a completed run and emit findings (tier-gated, gated)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver: _Resolver,
        connector: TargetConnector,
    ) -> None:
        self._session = session
        self._resolver = resolver
        self._connector = connector
        self._findings = FindingRepository(session)
        self._members = FindingResultRepository(session)

    async def run(
        self,
        *,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        target_env_db_url: str,
        target_db_ephemeral: bool,
        results: Sequence[Result],
    ) -> DbStatePhaseReport:
        """Tier-gated DB-state phase. Never raises into the run (defensive)."""
        project = await ProjectRepository(self._session).get(project_id)
        tier = DbStateTier(project.db_state_tier) if project else DbStateTier.OFF
        if tier is DbStateTier.OFF:
            return DbStatePhaseReport(tier=DbStateTier.OFF)

        target = DisposableTarget(
            url=target_env_db_url, disposable=target_db_ephemeral, label=str(project_id)
        )
        executor = DbStateExecutor(tier=tier, target=target)

        # FULL is the write-capable mode → the safety gate runs BEFORE we connect.
        # A prod/unflagged target refuses the DB-state portion without crashing.
        if tier is DbStateTier.FULL:
            try:
                executor.ensure_writable()
            except DbStateError as exc:
                logger.warning(
                    "db_state.refused",
                    extra={"project_id": str(project_id), "reason": str(exc)},
                )
                return DbStatePhaseReport(tier=tier, refused=True, reason=str(exc))

        anchor = self._anchor_result(results)
        if anchor is None:
            return DbStatePhaseReport(tier=tier, checks_run=0)

        checks = await derive_checks(self._session, project_id)
        emitted: list[uuid.UUID] = []
        try:
            async with self._connector.connect(
                read_only=tier is DbStateTier.READ_ONLY
            ) as conn:
                for spec in checks:
                    executor.ensure_readable()
                    tied = await executor.tie_to_table_node(
                        self._session, project_id, spec.check
                    )
                    result = await executor.assert_state(conn, tied)
                    if not result.passed:
                        finding_id = await self._emit(
                            project_id, run_id, anchor, spec, tied, result
                        )
                        emitted.append(finding_id)
        except DbStateError as exc:  # defense in depth — a gate slip refuses, no crash
            logger.warning(
                "db_state.refused_mid_phase",
                extra={"project_id": str(project_id), "reason": str(exc)},
            )
            return DbStatePhaseReport(
                tier=tier,
                emitted_finding_ids=tuple(emitted),
                checks_run=len(emitted),
                refused=True,
                reason=str(exc),
            )

        logger.info(
            "db_state.phase_completed",
            extra={
                "project_id": str(project_id),
                "run_id": str(run_id),
                "tier": tier.value,
                "checks": len(checks),
                "findings": len(emitted),
            },
        )
        return DbStatePhaseReport(
            tier=tier,
            emitted_finding_ids=tuple(emitted),
            checks_run=len(checks),
        )

    @staticmethod
    def _anchor_result(results: Sequence[Result]) -> Result | None:
        """A deterministic result from the run to anchor DB-state findings to.

        A DB-state finding is a consequence of the run's tests; it references one of
        the run's results for the (non-null) FK + evidence join. Deterministic-first
        by id so re-assembly is stable.
        """
        if not results:
            return None
        return min(results, key=lambda r: str(r.id))

    async def _emit(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        anchor: Result,
        spec: DbStateRunCheck,
        check: TableStateCheck,
        result: Any,
    ) -> uuid.UUID:
        subgraph = await self._resolver.journey(project_id, spec.endpoint_node_id)
        location = _location_from_subgraph(subgraph)
        # Tie to the table node at the deepest end even if the journey missed it.
        if check.table not in (location.get("tables") or []):
            location.setdefault("tables", []).append(check.table)
        anchor_key = f"db_state:{check.table}:{check.predicate.value}"
        root_cause_key = f"{anchor_key}#{check.oracle_source.value}"
        finding = await self._findings.add(
            Finding(
                project_id=project_id,
                run_id=run_id,
                result_id=anchor.id,
                root_cause_key=root_cause_key,
                explains_count=1,
                title=f"DB-state failure at table {check.table}",
                layer=FindingLayer.DB,
                oracle_source=check.oracle_source,
                confidence_mixed=False,
                expected={
                    "predicate": check.predicate.value,
                    "table": check.table,
                    "where": check.where,
                },
                evidence_ref=result.detail,
                location=location,
                severity=SEVERITY_UNSET,
                status=STATUS_OPEN,
            )
        )
        await self._members.add(
            FindingResult(
                project_id=project_id, finding_id=finding.id, result_id=anchor.id
            )
        )
        return finding.id
