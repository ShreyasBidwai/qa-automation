"""Finding-detail field assembly (finding-detail drawer).

Covers the pure field mappers (location anchor / evidence summary / history) in
isolation, then the batched ``FindingDetailReader`` against seeded runs: evidence
carries each failing test's ``oracle_source``, history reflects regression vs new,
and the whole-run read stays batched (no N+1).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.enums import FindingLayer, OracleSource, Outcome
from app.models.finding import Finding
from app.models.finding_result import FindingResult
from app.reporting import HistoryClassifier
from app.reporting.finding_detail import (
    FindingDetailReader,
    evidence_summary,
    history_payload,
    location_anchor,
    location_payload,
)
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_result_repository import FindingResultRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case

_BASE_DAY = datetime(2026, 1, 1, tzinfo=UTC)


# --- pure field mappers ------------------------------------------------------


class LocationMappersTests:
    def test_anchor_prefers_the_deepest_node(self) -> None:
        location = {
            "page": "/checkout",
            "endpoints": ["POST api/orders"],
            "tables": ["orders", "audit"],
        }
        anchor = location_anchor(location)
        assert anchor["node_type"] == "table"
        # deterministic: tables are sorted into the identifier
        assert anchor["identifier"] == "audit, orders"
        assert anchor["label"] == "audit, orders"

    def test_anchor_falls_back_endpoint_then_page(self) -> None:
        assert location_anchor({"endpoints": ["GET api/x"]})["node_type"] == "endpoint"
        assert location_anchor({"page": "/p"})["node_type"] == "page"

    def test_anchor_of_empty_location_is_unresolved(self) -> None:
        anchor = location_anchor({})
        assert anchor["node_type"] is None
        assert anchor["identifier"] is None
        assert anchor["label"] == "Location not resolved"

    def test_payload_carries_anchor_and_the_full_path(self) -> None:
        payload = location_payload(
            {"page": "/p", "endpoints": ["GET api/x"], "tables": ["t"]}
        )
        # anchor is the deepest node (table), the path carries every layer
        assert payload["anchor"]["node_type"] == "table"
        assert payload["page"] == "/p"
        assert payload["endpoints"] == ["GET api/x"]
        assert payload["tables"] == ["t"]


class EvidenceSummaryTests:
    def test_summarizes_status_and_assertion_kinds(self) -> None:
        summary = evidence_summary(
            Outcome.FAIL,
            {"status": 500, "assertions": [{"kind": "body"}, {"kind": "status"}]},
        )
        assert summary == "Failed — expected status 500; checks body, status"

    def test_errored_result_reads_errored(self) -> None:
        summary = evidence_summary(Outcome.ERROR, {})
        assert summary == "Errored — no recorded expectation"

    def test_failure_without_expectation_is_honest(self) -> None:
        assert evidence_summary(Outcome.FAIL, {}) == "Failed — no recorded expectation"


class HistoryPayloadTests:
    def test_new_finding_occurs_once_seen_now(self) -> None:
        run = uuid.uuid4()
        payload = history_payload("new", [uuid.uuid4(), uuid.uuid4()], set(), run)
        assert payload["classification"] == "new"
        assert payload["occurrence_count"] == 1
        assert payload["first_seen_run"] == run  # never seen before → current run
        assert payload["last_seen_run"] == run

    def test_recurring_finding_counts_priors_and_first_seen(self) -> None:
        old, middle, current = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        payload = history_payload("regression", [old, middle], {old}, current)
        assert payload["occurrence_count"] == 2  # one prior + the current run
        assert payload["first_seen_run"] == old
        assert payload["last_seen_run"] == current


# --- batched reader against seeded runs --------------------------------------


@pytest_asyncio.fixture
async def project_id(db_session: AsyncSession) -> uuid.UUID:
    project = await ProjectRepository(db_session).add(make_project())
    return project.id


async def _seed_finding(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    key: str,
    location: dict,
    oracle: OracleSource,
    expected: dict,
    outcome: Outcome = Outcome.FAIL,
    evidence_ref: str | None = "ev/trace.zip",
) -> Finding:
    case = await TestCaseRepository(session).add(
        make_test_case(
            project_id,
            target_node=uuid.uuid4(),
            oracle_source=oracle,
            expected=expected,
        )
    )
    result = await ResultRepository(session).add(
        make_result(
            project_id, run_id, case.id, outcome=outcome, evidence_ref=evidence_ref
        )
    )
    finding = await FindingRepository(session).add(
        Finding(
            project_id=project_id,
            run_id=run_id,
            result_id=result.id,
            root_cause_key=key,
            explains_count=1,
            title=f"finding {key}",
            layer=FindingLayer.API,
            oracle_source=oracle,
            confidence_mixed=False,
            expected=expected,
            location=location,
            severity="major",
            status="new",
        )
    )
    await FindingResultRepository(session).add(
        FindingResult(project_id=project_id, finding_id=finding.id, result_id=result.id)
    )
    return finding


async def test_detail_exposes_location_evidence_and_history(
    db_session: AsyncSession, project_id: uuid.UUID
) -> None:
    run = await RunRepository(db_session).add(
        make_run(project_id, created_at=_BASE_DAY)
    )
    finding = await _seed_finding(
        db_session,
        project_id,
        run.id,
        key="endpoint=POST api/orders#fail|status=500",
        location={
            "page": "/checkout",
            "endpoints": ["POST api/orders"],
            "tables": ["orders"],
        },
        oracle=OracleSource.SPEC_GROUNDED,
        expected={"status": 500, "assertions": [{"kind": "status"}]},
    )

    detail = await FindingDetailReader(db_session).detail_for(
        project_id, run.id, [finding]
    )
    bundle = detail[finding.id]

    # location: anchor (the DEEPEST node — table beats endpoint/page) + the full
    # blast path for the ribbon
    assert bundle.location["anchor"]["node_type"] == "table"
    assert bundle.location["anchor"]["identifier"] == "orders"
    assert bundle.location["page"] == "/checkout"
    assert bundle.location["endpoints"] == ["POST api/orders"]
    assert bundle.location["tables"] == ["orders"]

    # evidence: a what-failed summary + the per-assertion trust signal
    assert len(bundle.evidence) == 1
    item = bundle.evidence[0]
    assert item["oracle_source"] == "spec-grounded"
    assert item["summary"] == "Failed — expected status 500; checks status"
    assert item["reference"] == "ev/trace.zip"

    # history: classified + supporting fields (single run → seen once)
    assert bundle.history["classification"] == "new"
    assert bundle.history["occurrence_count"] == 1
    assert bundle.history["first_seen_run"] == run.id


async def test_history_distinguishes_regression_from_new(
    db_session: AsyncSession, project_id: uuid.UUID
) -> None:
    recurring = "endpoint=POST api/orders#fail|status=500"
    runs = RunRepository(db_session)
    # R0 has the bug, R1 cleared it, R2 (current) brings it back → regression.
    r0 = await runs.add(make_run(project_id, created_at=_BASE_DAY))
    await runs.add(make_run(project_id, created_at=_BASE_DAY + timedelta(days=1)))
    r2 = await runs.add(make_run(project_id, created_at=_BASE_DAY + timedelta(days=2)))

    location = {"endpoints": ["POST api/orders"]}
    await _seed_finding(
        db_session,
        project_id,
        r0.id,
        key=recurring,
        location=location,
        oracle=OracleSource.RULE_DERIVED,
        expected={"status": 500},
    )
    regression = await _seed_finding(
        db_session,
        project_id,
        r2.id,
        key=recurring,
        location=location,
        oracle=OracleSource.RULE_DERIVED,
        expected={"status": 500},
    )
    fresh = await _seed_finding(
        db_session,
        project_id,
        r2.id,
        key="endpoint=GET api/new#fail",
        location={"endpoints": ["GET api/new"]},
        oracle=OracleSource.CHARACTERIZATION,
        expected={},
    )

    # The classifier sets each finding's status; the reader surfaces it + counts.
    await HistoryClassifier(db_session).classify_run(project_id, r2.id)
    detail = await FindingDetailReader(db_session).detail_for(
        project_id, r2.id, [regression, fresh]
    )

    regression_history = detail[regression.id].history
    assert regression_history["classification"] == "regression"
    assert regression_history["occurrence_count"] == 2  # R0 + R2
    assert regression_history["first_seen_run"] == r0.id
    assert regression_history["last_seen_run"] == r2.id

    fresh_history = detail[fresh.id].history
    assert fresh_history["classification"] == "new"
    assert fresh_history["occurrence_count"] == 1
    assert fresh_history["first_seen_run"] == r2.id


def test_evidence_for_handles_missing_result_and_case() -> None:
    """The defensive branches: a dropped result is skipped; a missing case
    falls back to the finding's oracle source."""
    finding = Finding(
        project_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        result_id=uuid.uuid4(),
        root_cause_key="endpoint=x#fail",
        explains_count=1,
        title="t",
        layer=FindingLayer.API,
        oracle_source=OracleSource.RULE_DERIVED,
        confidence_mixed=False,
        expected={},
        location={},
        severity="major",
        status="new",
    )
    present = uuid.uuid4()
    result = make_result(
        finding.project_id, finding.run_id, uuid.uuid4(), outcome=Outcome.FAIL
    )
    # one resolvable result (no case in the map) + one dangling id
    evidence = FindingDetailReader._evidence_for(
        [present, uuid.uuid4()], {present: result}, {}, finding
    )
    assert len(evidence) == 1  # the dangling id is skipped
    assert evidence[0]["oracle_source"] == "rule-derived"  # finding's source


@pytest_asyncio.fixture
async def counting_session(
    test_database_url: str,
) -> AsyncIterator[tuple[AsyncSession, list[int]]]:
    """A rolled-back session plus a live SQL statement counter (for N+1 checks)."""
    engine = create_async_engine(test_database_url)
    calls: list[int] = []

    def _count(*_args: object) -> None:
        calls.append(1)

    event.listen(engine.sync_engine, "before_cursor_execute", _count)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session, calls
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _count)
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def test_detail_read_is_batched_no_n_plus_one(
    counting_session: tuple[AsyncSession, list[int]],
) -> None:
    session, calls = counting_session
    project = await ProjectRepository(session).add(make_project())
    run = await RunRepository(session).add(make_run(project.id, created_at=_BASE_DAY))

    findings = [
        await _seed_finding(
            session,
            project.id,
            run.id,
            key=f"endpoint=POST api/r{i}#fail|status=500",
            location={"endpoints": [f"POST api/r{i}"], "tables": ["orders"]},
            oracle=OracleSource.RULE_DERIVED,
            expected={"status": 500, "assertions": [{"kind": "status"}]},
        )
        for i in range(3)
    ]

    reader = FindingDetailReader(session)

    calls.clear()
    await reader.detail_for(project.id, run.id, findings[:1])
    one = len(calls)

    calls.clear()
    await reader.detail_for(project.id, run.id, findings)
    many = len(calls)

    # Reading three findings costs the same fixed number of queries as one —
    # the reads are batched, so there is no per-finding query (no N+1).
    assert one == many
    assert many <= 8


async def test_detail_for_no_findings_is_empty(
    db_session: AsyncSession, project_id: uuid.UUID
) -> None:
    detail = await FindingDetailReader(db_session).detail_for(
        project_id, uuid.uuid4(), []
    )
    assert detail == {}
