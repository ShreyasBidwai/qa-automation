"""Cross-run history classification (T7.4) — fast tests.

Pure classification of a presence vector (new/known/regression/flaky with
precedence flaky > regression > known > new, ADR-0023) plus DB integration with
injected prior-run findings: a key's status is derived from a bounded window of
the project's prior runs joined on root_cause_key, deterministically and
project-scoped, and persisted into the existing status column.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FindingLayer, FindingStatus, OracleSource, Outcome
from app.models.finding import Finding
from app.reporting.history import HistoryClassifier, classify_history
from app.repositories.finding_repository import FindingRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


# --- pure classification -----------------------------------------------------


def test_unseen_key_is_new() -> None:
    assert classify_history([]) is FindingStatus.NEW
    assert classify_history([False, False, False]) is FindingStatus.NEW


def test_present_in_immediately_prior_run_is_known() -> None:
    assert classify_history([True]) is FindingStatus.KNOWN
    assert classify_history([False, True]) is FindingStatus.KNOWN
    assert classify_history([True, True]) is FindingStatus.KNOWN


def test_cleared_then_back_is_regression() -> None:
    assert classify_history([True, False]) is FindingStatus.REGRESSION
    assert classify_history([True, True, False]) is FindingStatus.REGRESSION


def test_oscillation_is_flaky() -> None:
    assert classify_history([True, False, True]) is FindingStatus.FLAKY  # 2 flips
    assert classify_history([False, True, False, True]) is FindingStatus.FLAKY


def test_flaky_wins_over_regression() -> None:
    presence = [True, False, True, False]
    # regression-eligible (seen earlier, absent in the immediately-prior run)...
    assert any(presence) and not presence[-1]
    # ...but it oscillated, so flaky wins (precedence).
    assert classify_history(presence) is FindingStatus.FLAKY


def test_single_flip_is_regression_not_flaky() -> None:
    assert classify_history([True, False]) is FindingStatus.REGRESSION


# --- DB fixtures -------------------------------------------------------------


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _run(session: AsyncSession, project_id: uuid.UUID, hour: int) -> uuid.UUID:
    # Explicit, increasing timestamps: within one transaction now() is constant,
    # so fixtures must order runs themselves (ADR-0023).
    run = await RunRepository(session).add(
        make_run(project_id, created_at=_BASE + timedelta(hours=hour))
    )
    return run.id


async def _seed_finding(
    session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID, key: str
) -> Finding:
    """A finding (with its backing case + result) for ``key`` in ``run_id``."""
    case = await TestCaseRepository(session).add(make_test_case(project_id))
    result = await ResultRepository(session).add(
        make_result(project_id, run_id, case.id, outcome=Outcome.FAIL)
    )
    return await FindingRepository(session).add(
        Finding(
            project_id=project_id,
            run_id=run_id,
            result_id=result.id,
            root_cause_key=key,
            explains_count=1,
            title="finding",
            layer=FindingLayer.API,
            oracle_source=OracleSource.RULE_DERIVED,
            confidence_mixed=False,
            expected={},
            location={},
            severity="unset",
            status="open",
        )
    )


# --- DB classification -------------------------------------------------------


async def test_new_when_key_has_no_prior_history(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    run = await _run(db_session, project_id, 1)
    finding = await _seed_finding(db_session, project_id, run, "K")
    assert await HistoryClassifier(db_session).classify(project_id, finding) is (
        FindingStatus.NEW
    )


async def test_known_when_key_in_prior_run(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    prior = await _run(db_session, project_id, 1)
    current = await _run(db_session, project_id, 2)
    await _seed_finding(db_session, project_id, prior, "K")
    finding = await _seed_finding(db_session, project_id, current, "K")
    assert await HistoryClassifier(db_session).classify(project_id, finding) is (
        FindingStatus.KNOWN
    )


async def test_regression_when_cleared_then_back(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    r1 = await _run(db_session, project_id, 1)  # K present
    r2 = await _run(db_session, project_id, 2)  # exists, failed differently (no K)
    r3 = await _run(db_session, project_id, 3)  # current, K back
    await _seed_finding(db_session, project_id, r1, "K")
    await _seed_finding(db_session, project_id, r2, "OTHER")  # other keys don't count
    finding = await _seed_finding(db_session, project_id, r3, "K")
    assert await HistoryClassifier(db_session).classify(project_id, finding) is (
        FindingStatus.REGRESSION
    )


async def test_flaky_when_key_oscillates(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    r1 = await _run(db_session, project_id, 1)  # K
    await _run(db_session, project_id, 2)  # no K
    r3 = await _run(db_session, project_id, 3)  # K
    await _run(db_session, project_id, 4)  # no K
    r5 = await _run(db_session, project_id, 5)  # current, K
    await _seed_finding(db_session, project_id, r1, "K")
    await _seed_finding(db_session, project_id, r3, "K")
    finding = await _seed_finding(db_session, project_id, r5, "K")
    # window [r1,r2,r3,r4] presence [T,F,T,F] → 3 flips → flaky (wins over regression)
    assert await HistoryClassifier(db_session).classify(project_id, finding) is (
        FindingStatus.FLAKY
    )


async def test_bounded_window_excludes_older_runs(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    r1 = await _run(db_session, project_id, 1)  # K — but outside a window of 2
    await _run(db_session, project_id, 2)  # no K
    await _run(db_session, project_id, 3)  # no K
    r4 = await _run(db_session, project_id, 4)  # current, K
    await _seed_finding(db_session, project_id, r1, "K")
    finding = await _seed_finding(db_session, project_id, r4, "K")

    # window of 2 → prior [r2, r3] presence [F, F] → new (r1 is out of window)
    assert (
        await HistoryClassifier(db_session, window=2).classify(project_id, finding)
        is FindingStatus.NEW
    )
    # a wider window sees r1 → cleared then back → regression
    assert (
        await HistoryClassifier(db_session, window=10).classify(project_id, finding)
        is FindingStatus.REGRESSION
    )


async def test_classification_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    # Project B has a prior history for K...
    b_prior = await _run(db_session, project_b, 1)
    await _seed_finding(db_session, project_b, b_prior, "K")
    # ...but project A's first sighting of K must still be new.
    a_run = await _run(db_session, project_a, 2)
    finding = await _seed_finding(db_session, project_a, a_run, "K")
    assert await HistoryClassifier(db_session).classify(project_a, finding) is (
        FindingStatus.NEW
    )


async def test_unknown_run_classifies_as_new(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    # An in-memory finding whose run does not exist → no window → new.
    finding = Finding(
        project_id=project_id,
        run_id=uuid.uuid4(),
        result_id=uuid.uuid4(),
        root_cause_key="K",
        explains_count=1,
        title="finding",
        layer=FindingLayer.API,
        oracle_source=OracleSource.RULE_DERIVED,
        confidence_mixed=False,
        expected={},
        location={},
        severity="unset",
        status="open",
    )
    assert await HistoryClassifier(db_session).classify(project_id, finding) is (
        FindingStatus.NEW
    )


async def test_classify_run_persists_status(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    prior = await _run(db_session, project_id, 1)
    current = await _run(db_session, project_id, 2)
    await _seed_finding(db_session, project_id, prior, "K")
    finding = await _seed_finding(db_session, project_id, current, "K")

    classified = await HistoryClassifier(db_session).classify_run(project_id, current)

    assert [f.status for f in classified] == ["known"]
    reloaded = await FindingRepository(db_session).get(project_id, finding.id)
    assert reloaded is not None and reloaded.status == "known"  # persisted
