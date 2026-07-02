"""Heal ↔ findings reconciliation (ADR-0041).

A LOCATION failure that has an active heal is addressing drift, not a broken app:
it is suppressed from the default open-findings inbox (reachable via the heals list
or ``include_superseded``) and tagged ``superseded_by_heal`` wherever it surfaces. A
real assertion finding has no heal and is NEVER suppressed; a rejected heal
un-suppresses its finding. Deterministic, no N+1.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FindingLayer, OracleSource, Outcome
from app.models.finding import Finding
from app.models.test_heal import (
    STATUS_CONFIRMED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    TestHeal,
)
from app.reporting.heal_reconciliation import superseded_finding_ids
from app.reporting.open_findings import OpenFindingsReader
from app.repositories.finding_repository import FindingRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _seed_finding(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    key: str,
    heal_status: str | None = None,
) -> Finding:
    """A failing result → a Finding, optionally with a heal on its test case."""
    case = await TestCaseRepository(session).add(make_test_case(project_id))
    result = await ResultRepository(session).add(
        make_result(project_id, run_id, case.id, outcome=Outcome.FAIL)
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
            oracle_source=OracleSource.RULE_DERIVED,
            confidence_mixed=False,
            expected={},
            location={},
            severity="major",
            status="new",
        )
    )
    if heal_status is not None:
        session.add(
            TestHeal(
                project_id=project_id,
                run_id=run_id,
                test_case_id=case.id,
                kind="route_rebind",
                failure_class="location",
                before_addr="api/users",
                after_addr="api/people",
                rationale="route moved",
                confidence="high",
                status=heal_status,
                healed_code="<?php // healed",
            )
        )
        await session.flush()
    return finding


# --- the reconciliation rule (reader-level) ----------------------------------


async def test_healed_location_finding_suppressed_by_default(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = (await RunRepository(db_session).add(make_run(project_id))).id
    await _seed_finding(
        db_session, project_id, run_id, key="DRIFT#fail", heal_status=STATUS_CONFIRMED
    )
    await _seed_finding(db_session, project_id, run_id, key="REAL#fail")

    page, total = await OpenFindingsReader(db_session).open_findings(
        project_id, limit=100, offset=0
    )

    # Only the real finding is "currently broken"; the CONFIRMED-healed drift is
    # suppressed.
    assert total == 1
    assert [i.finding.root_cause_key for i in page] == ["REAL#fail"]
    assert page[0].superseded is False


async def test_include_superseded_returns_it_tagged(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = (await RunRepository(db_session).add(make_run(project_id))).id
    await _seed_finding(
        db_session, project_id, run_id, key="DRIFT#fail", heal_status=STATUS_CONFIRMED
    )
    await _seed_finding(db_session, project_id, run_id, key="REAL#fail")

    page, total = await OpenFindingsReader(db_session).open_findings(
        project_id, limit=100, offset=0, include_superseded=True
    )

    assert total == 2
    by_key = {i.finding.root_cause_key: i for i in page}
    assert by_key["DRIFT#fail"].superseded is True  # still reachable, tagged
    assert by_key["REAL#fail"].superseded is False


async def test_proposed_heal_does_not_suppress(db_session: AsyncSession) -> None:
    # A PROPOSED (unconfirmed) heal must NOT hide the finding — the human still needs
    # to see it to accept/reject the re-addressing (architecture-review DO-NEXT #10).
    project_id = await _project(db_session)
    run_id = (await RunRepository(db_session).add(make_run(project_id))).id
    finding = await _seed_finding(
        db_session, project_id, run_id, key="DRIFT#fail", heal_status=STATUS_PROPOSED
    )
    assert await superseded_finding_ids(db_session, [finding]) == set()

    page, total = await OpenFindingsReader(db_session).open_findings(
        project_id, limit=100, offset=0
    )
    assert total == 1 and page[0].finding.root_cause_key == "DRIFT#fail"


async def test_rejected_heal_does_not_suppress(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    run_id = (await RunRepository(db_session).add(make_run(project_id))).id
    finding = await _seed_finding(
        db_session, project_id, run_id, key="STANDS#fail", heal_status=STATUS_REJECTED
    )

    superseded = await superseded_finding_ids(db_session, [finding])
    assert superseded == set()  # the human rejected the heal → it's a real finding

    page, total = await OpenFindingsReader(db_session).open_findings(
        project_id, limit=100, offset=0
    )
    assert total == 1 and page[0].finding.root_cause_key == "STANDS#fail"


async def test_superseded_ids_of_no_findings_is_empty(
    db_session: AsyncSession,
) -> None:
    assert await superseded_finding_ids(db_session, []) == set()


async def test_assertion_finding_is_never_suppressed(
    db_session: AsyncSession,
) -> None:
    """A finding with no heal (a real assertion failure) is always surfaced."""
    project_id = await _project(db_session)
    run_id = (await RunRepository(db_session).add(make_run(project_id))).id
    finding = await _seed_finding(db_session, project_id, run_id, key="BUG#fail")

    assert await superseded_finding_ids(db_session, [finding]) == set()
    page, total = await OpenFindingsReader(db_session).open_findings(
        project_id, limit=100, offset=0
    )
    assert total == 1 and page[0].superseded is False


# --- the additive API contract (end to end) ----------------------------------


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_inbox_excludes_drift_by_default_includes_tagged_with_flag(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    """End-to-end additive contract: a real finding shows, addressing drift is
    suppressed by default and reachable+tagged via ``include_superseded``.

    Per-test isolation (ADR-0042) rolls back what this commits, so it can seed the
    realistic mix (a real OPEN finding alongside the healed one) without leaking into
    other tests' global reads — the prior workaround (seeding only the healed finding)
    is no longer needed."""
    client, app = app_client
    email = f"recon-{uuid.uuid4().hex[:12]}@example.test"
    signup = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "passw0rd1"}
    )
    token = signup.json()["access_token"]
    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"name": "Recon", "repo_url": "https://git/recon.git"},
            headers=_h(token),
        )
    ).json()["id"]

    async with app.state.sessionmaker() as session:
        pid = uuid.UUID(project_id)
        run_id = (
            await RunRepository(session).add(
                make_run(pid, created_at=datetime(2026, 6, 1, tzinfo=UTC))
            )
        ).id
        await _seed_finding(
            session, pid, run_id, key="DRIFT#fail", heal_status=STATUS_CONFIRMED
        )
        await _seed_finding(session, pid, run_id, key="REAL#fail")
        await session.commit()

    base = f"/api/v1/projects/{project_id}/findings"
    # Default inbox: only the real failure; the addressing drift is suppressed
    # (it reads as "test needs re-addressing", not "the app is broken").
    default = (await client.get(base, headers=_h(token))).json()
    assert default["total"] == 1
    assert default["items"][0]["root_cause_key"] == "REAL#fail"
    assert default["items"][0]["superseded_by_heal"] is False

    # Opt in: the drift is reachable, carrying the additive ``superseded_by_heal`` tag.
    included = (
        await client.get(f"{base}?include_superseded=true", headers=_h(token))
    ).json()
    assert included["total"] == 2
    drift = next(i for i in included["items"] if i["root_cause_key"] == "DRIFT#fail")
    assert drift["superseded_by_heal"] is True
    assert "models" in drift["location"]  # the widened blast-path field is present
