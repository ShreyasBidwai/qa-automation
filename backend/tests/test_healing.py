"""Honest self-healing (B8, ADR-0040) — service + endpoints, end to end.

The gate scenarios: a location failure is healed (proposed); an assertion failure
is NEVER healed and surfaces as a finding (the safety test); a low-confidence
re-binding is reported, not applied; a healed test is lower-trust until confirmed;
confirm/reject are RBAC-gated; re-scanning is idempotent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.healing.service import HealService
from app.models.enums import Framework, NodeKind, OrgRole, Outcome
from app.models.organization import Organization
from app.models.project import Project
from app.repositories.node_repository import NodeRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.test_heal_repository import TestHealRepository
from app.repositories.test_script_repository import TestScriptRepository
from tests.factories import (
    make_node,
    make_project,
    make_result,
    make_run,
    make_test_case,
    make_test_script,
)

# A directly-runnable test addressing the OLD route. A heal re-points the call;
# the assertion is the protected block and must survive byte-identical.
_PEST = """<?php
test('create a user', function () {
    $r = $this->postJson('/api/users', ['name' => 'Ada', 'email' => 'a@b.test']);
    $r->assertStatus(201);
});
"""

# A 404 the test received — the route moved (a location failure → candidate heal).
LOC_404 = "Expected response status code [201] but received [404]."
# A 500 the test received — reached and broke (an assertion failure → never healed).
ASSERT_500 = (
    "Expected response status code [201] but received [500]. "
    "Failed asserting that 500 is identical to 201."
)


async def _seed(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    message: str,
    case_route_name: str | None = "users.store",
    node_uris: tuple[str, ...] = ("api/people",),
    node_route_name: str = "users.store",
    old_uri: str = "api/users",
    method: str = "POST",
    pass_before: bool = True,
    script_code: str = _PEST,
    with_script: bool = True,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a moved-route scenario; return (case_id, current_run_id).

    Brain endpoint nodes sit at each of ``node_uris`` (the re-ingested locations;
    pass ``()`` for "no code model"); a current test addresses ``old_uri``; a prior
    run passed and the current run failed with ``message``.
    """
    for node_uri in node_uris:
        await NodeRepository(session).add(
            make_node(
                project_id,
                kind=NodeKind.ENDPOINT,
                name=f"{method} {node_uri}",
                attributes={
                    "method": method,
                    "uri": node_uri,
                    "name": node_route_name,
                },
            )
        )
    case = make_test_case(
        project_id,
        preconditions={
            "endpoint": {
                "method": method,
                "uri": old_uri,
                "route_name": case_route_name,
            }
        },
        case_key=f"{method} /{old_uri}::happy::create",
    )
    session.add(case)
    await session.flush()
    if with_script:
        session.add(
            make_test_script(
                project_id, case.id, framework=Framework.PEST, code=script_code
            )
        )
    prior = make_run(
        project_id, status="failed", created_at=datetime(2026, 6, 1, tzinfo=UTC)
    )
    current = make_run(
        project_id, status="failed", created_at=datetime(2026, 6, 2, tzinfo=UTC)
    )
    session.add_all([prior, current])
    await session.flush()
    if pass_before:
        session.add(
            make_result(project_id, prior.id, case.id, outcome=Outcome.PASS)
        )
    session.add(
        make_result(
            project_id, current.id, case.id, outcome=Outcome.FAIL, message=message
        )
    )
    await session.flush()
    return case.id, current.id


# --- service: the deterministic heal/no-heal decision ------------------------


async def test_location_failure_proposes_a_heal(db_session: AsyncSession) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    case_id, run_id = await _seed(db_session, project.id, message=LOC_404)

    report = await HealService(db_session).scan_run(project.id, run_id)

    assert report.summary == {"healed": 1, "real_findings": 0, "unhealed": 0}
    heal = report.healed[0]
    assert heal.status == "proposed" and heal.confidence == "high"
    assert heal.kind == "route_rebind" and heal.failure_class == "location"
    assert heal.before_addr == "api/users" and heal.after_addr == "api/people"
    # the re-addressed code points at the new route; the assertion is preserved.
    assert "/api/people" in heal.healed_code and "/api/users" not in heal.healed_code
    assert "assertStatus(201)" in heal.healed_code
    # flagged, never silent: the LIVE script is untouched until a human confirms.
    scripts = await TestScriptRepository(db_session).list_for_test_case(
        project.id, case_id
    )
    assert "/api/users" in scripts[-1].code


async def test_assertion_failure_is_never_healed(db_session: AsyncSession) -> None:
    """The safety test: even though the route moved (re-resolvable), an assertion
    failure is a real finding and must NEVER be healed."""
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    case_id, run_id = await _seed(db_session, project.id, message=ASSERT_500)

    report = await HealService(db_session).scan_run(project.id, run_id)

    assert report.summary == {"healed": 0, "real_findings": 1, "unhealed": 0}
    assert report.real_findings == [case_id]
    assert await TestHealRepository(db_session).count(project.id) == 0


async def test_low_confidence_is_reported_not_healed(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    # No route-name match; only a same-method, same-last-segment node exists → a
    # low-confidence structural guess, below the heal bar.
    _case_id, run_id = await _seed(
        db_session,
        project.id,
        message=LOC_404,
        case_route_name=None,
        node_uris=("api/v2/users",),
    )

    report = await HealService(db_session).scan_run(project.id, run_id)

    assert report.summary == {"healed": 0, "real_findings": 0, "unhealed": 1}
    assert await TestHealRepository(db_session).count(project.id) == 0


async def test_previously_failing_test_is_not_a_candidate(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    # The same 404, but the test was never green before → out of scope entirely.
    _case_id, run_id = await _seed(
        db_session, project.id, message=LOC_404, pass_before=False
    )

    report = await HealService(db_session).scan_run(project.id, run_id)

    assert report.summary == {"healed": 0, "real_findings": 0, "unhealed": 0}


async def test_rescan_is_idempotent(db_session: AsyncSession) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    _case_id, run_id = await _seed(db_session, project.id, message=LOC_404)
    service = HealService(db_session)

    first = await service.scan_run(project.id, run_id)
    second = await service.scan_run(project.id, run_id)

    assert first.summary["healed"] == 1 and second.summary["healed"] == 1
    assert first.healed[0].id == second.healed[0].id  # the same row, not a duplicate
    assert await TestHealRepository(db_session).count(project.id) == 1


async def test_reject_leaves_the_live_test_untouched(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    case_id, run_id = await _seed(db_session, project.id, message=LOC_404)
    service = HealService(db_session)
    heal = (await service.scan_run(project.id, run_id)).healed[0]

    rejected = await service.reject_heal(
        project.id, heal.id, resolved_by="me@example.test"
    )

    assert rejected is not None and rejected.status == "rejected"
    scripts = await TestScriptRepository(db_session).list_for_test_case(
        project.id, case_id
    )
    assert "/api/users" in scripts[-1].code  # never re-addressed


async def test_deleted_route_is_not_healed(db_session: AsyncSession) -> None:
    """A 404 with no re-bindable target in the Brain is a real regression, not a
    move — we report it honestly, we do not guess."""
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    _case_id, run_id = await _seed(
        db_session, project.id, message=LOC_404, node_uris=()  # no code endpoints
    )

    report = await HealService(db_session).scan_run(project.id, run_id)

    assert report.summary == {"healed": 0, "real_findings": 0, "unhealed": 1}
    assert await TestHealRepository(db_session).count(project.id) == 0


async def test_ambiguous_route_name_is_not_healed(db_session: AsyncSession) -> None:
    """The route name maps to two different new URIs → ambiguous → never guessed."""
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    _case_id, run_id = await _seed(
        db_session,
        project.id,
        message=LOC_404,
        node_uris=("api/people", "api/humans"),  # same route_name, two locations
    )

    report = await HealService(db_session).scan_run(project.id, run_id)

    assert report.summary == {"healed": 0, "real_findings": 0, "unhealed": 1}


async def test_addressing_absent_from_script_is_not_healed(
    db_session: AsyncSession,
) -> None:
    """The target re-resolves, but the script doesn't address the old path we can
    rewrite → we decline rather than touch code we don't understand."""
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    other_script = _PEST.replace("api/users", "api/orders")
    _case_id, run_id = await _seed(
        db_session, project.id, message=LOC_404, script_code=other_script
    )

    report = await HealService(db_session).scan_run(project.id, run_id)

    assert report.summary == {"healed": 0, "real_findings": 0, "unhealed": 1}


async def test_confirm_applies_and_second_confirm_is_a_noop(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    case_id, run_id = await _seed(db_session, project.id, message=LOC_404)
    service = HealService(db_session)
    heal = (await service.scan_run(project.id, run_id)).healed[0]

    confirmed = await service.confirm_heal(
        project.id, heal.id, resolved_by="owner@example.test"
    )
    assert confirmed is not None and confirmed.status == "confirmed"
    assert confirmed.resolved_by == "owner@example.test"
    scripts = await TestScriptRepository(db_session).list_for_test_case(
        project.id, case_id
    )
    assert "/api/people" in scripts[-1].code  # the live test is re-addressed

    # confirming again is a harmless no-op (already resolved, not re-applied).
    again = await service.confirm_heal(
        project.id, heal.id, resolved_by="someone@else.test"
    )
    assert again is not None and again.status == "confirmed"
    assert again.resolved_by == "owner@example.test"  # unchanged


async def test_confirm_and_reject_missing_heal_return_none(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    service = HealService(db_session)
    missing = uuid.uuid4()
    assert await service.confirm_heal(project.id, missing, resolved_by="x") is None
    assert await service.reject_heal(project.id, missing, resolved_by="x") is None


# --- endpoints: scan → review (lower-trust) → confirm (apply) ----------------


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client: AsyncClient) -> tuple[str, uuid.UUID]:
    email = f"heal-{uuid.uuid4().hex[:12]}@example.test"
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "passw0rd1"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


async def _create_project(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Heal", "repo_url": "https://git/heal.git"},
        headers=_h(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_scan_confirm_flow_marks_lower_trust_until_confirmed(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    token, _ = await _signup(client)
    project_id = await _create_project(client, token)
    async with app.state.sessionmaker() as session:
        case_id, run_id = await _seed(
            session, uuid.UUID(project_id), message=LOC_404
        )
        await session.commit()

    scan = await client.post(
        f"/api/v1/projects/{project_id}/runs/{run_id}/heal-scan", headers=_h(token)
    )
    assert scan.status_code == 200, scan.text
    body = scan.json()
    assert (body["healed"], body["real_findings"], body["unhealed"]) == (1, 0, 0)
    heal = body["items"][0]
    # a freshly-proposed heal is lower-trust (awaiting review).
    assert heal["status"] == "proposed" and heal["trusted"] is False
    heal_id = heal["id"]

    queue = (
        await client.get(f"/api/v1/projects/{project_id}/heals", headers=_h(token))
    ).json()
    assert queue["total"] == 1

    confirm = await client.post(
        f"/api/v1/projects/{project_id}/heals/{heal_id}/confirm", headers=_h(token)
    )
    assert confirm.status_code == 200
    confirmed = confirm.json()
    assert confirmed["status"] == "confirmed" and confirmed["trusted"] is True

    # the live test is now re-addressed...
    async with app.state.sessionmaker() as session:
        scripts = await TestScriptRepository(session).list_for_test_case(
            uuid.UUID(project_id), case_id
        )
        assert "/api/people" in scripts[-1].code
        assert "/api/users" not in scripts[-1].code
    # ...and it has left the review queue.
    queue2 = (
        await client.get(f"/api/v1/projects/{project_id}/heals", headers=_h(token))
    ).json()
    assert queue2["total"] == 0


async def test_confirm_and_scan_are_rbac_gated(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    owner, owner_id = await _signup(client)
    viewer, viewer_id = await _signup(client)
    outsider, _ = await _signup(client)

    async with app.state.sessionmaker() as session:
        repo = OrganizationRepository(session)
        org = await repo.add(Organization(name="Team", is_personal=False))
        await repo.add_member(org.id, owner_id, OrgRole.OWNER)
        await repo.add_member(org.id, viewer_id, OrgRole.VIEWER)
        project = Project(
            name="P", slug=f"p-{uuid.uuid4().hex[:8]}", org_id=org.id, settings={}
        )
        session.add(project)
        await session.flush()
        project_id = project.id
        _case_id, run_id = await _seed(session, project_id, message=LOC_404)
        await session.commit()

    scan_url = f"/api/v1/projects/{project_id}/runs/{run_id}/heal-scan"
    heals_url = f"/api/v1/projects/{project_id}/heals"

    # owner scans (RUN) → a proposed heal.
    scan = await client.post(scan_url, headers=_h(owner))
    assert scan.status_code == 200
    heal_id = scan.json()["items"][0]["id"]
    confirm_url = f"/api/v1/projects/{project_id}/heals/{heal_id}/confirm"

    # viewer can read the queue but cannot scan (RUN) or confirm (MANAGE_PROJECT).
    assert (await client.get(heals_url, headers=_h(viewer))).status_code == 200
    assert (await client.post(scan_url, headers=_h(viewer))).status_code == 403
    assert (await client.post(confirm_url, headers=_h(viewer))).status_code == 403

    # a non-member gets 404 (existence is not leaked).
    assert (await client.get(heals_url, headers=_h(outsider))).status_code == 404
    assert (await client.post(confirm_url, headers=_h(outsider))).status_code == 404

    # owner (MANAGE_PROJECT) confirms.
    assert (await client.post(confirm_url, headers=_h(owner))).status_code == 200
