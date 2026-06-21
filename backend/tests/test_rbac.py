"""RBAC enforcement end-to-end (B3, ADR-0033).

The permission matrix (test_permissions.py) wired through the real endpoints: each
role × action, allow and deny, plus the leak-safe failure model — a non-member sees
404 (existence hidden), an in-org but under-privileged caller sees 403.

Setup commits an org + memberships + a project through the app's sessionmaker (the
GET endpoints read their own request session), and signs each persona in via the
API. The run executor/ingestor stubs are reused from test_api.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient

from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from tests.test_api import _StubExecutor, _StubIngestor

_RUN_BODY = {"mode": "mode_b", "strategy": "full_sweep"}


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _email() -> str:
    return f"rbac-{uuid.uuid4().hex[:12]}@example.test"


async def _signup(client: AsyncClient) -> tuple[str, uuid.UUID]:
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": _email(), "password": "passw0rd1"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


class _Scenario:
    def __init__(
        self,
        client: AsyncClient,
        tokens: dict[str, str],
        org_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        self.client = client
        self.tokens = tokens
        self.org_id = org_id
        self.project_id = project_id


@pytest_asyncio.fixture
async def scenario(app_client: tuple[AsyncClient, FastAPI]) -> _Scenario:
    """One team org with an owner/admin/member/viewer + a project, plus an
    outsider (in their own personal org only)."""
    client, app = app_client
    app.state.run_executor = _StubExecutor()
    app.state.ingestor = _StubIngestor()

    tokens: dict[str, str] = {}
    members: dict[OrgRole, uuid.UUID] = {}
    for persona, role in (
        ("owner", OrgRole.OWNER),
        ("admin", OrgRole.ADMIN),
        ("member", OrgRole.MEMBER),
        ("viewer", OrgRole.VIEWER),
    ):
        token, uid = await _signup(client)
        tokens[persona] = token
        members[role] = uid
    tokens["outsider"], _ = await _signup(client)

    async with app.state.sessionmaker() as session:
        repo = OrganizationRepository(session)
        org = await repo.add(Organization(name="Team", is_personal=False))
        org_id = org.id
        for role, uid in members.items():
            await repo.add_member(org_id, uid, role)
        project = Project(
            name="Team Project",
            slug=f"team-{uuid.uuid4().hex[:8]}",
            org_id=org_id,
            settings={"repo_url": "https://git/team.git"},
        )
        session.add(project)
        await session.flush()
        project_id = project.id
        await session.commit()

    return _Scenario(client, tokens, org_id, project_id)


async def test_view_permission(scenario: _Scenario) -> None:
    """Every member can VIEW; a non-member is 404 (not 403)."""
    path = f"/api/v1/projects/{scenario.project_id}"
    for persona in ("owner", "admin", "member", "viewer"):
        resp = await scenario.client.get(path, headers=_h(scenario.tokens[persona]))
        assert resp.status_code == 200, persona
    outsider = await scenario.client.get(path, headers=_h(scenario.tokens["outsider"]))
    assert outsider.status_code == 404  # existence not leaked


async def test_manage_project_permission(scenario: _Scenario) -> None:
    """owner/admin/member can edit; viewer → 403; outsider → 404."""
    path = f"/api/v1/projects/{scenario.project_id}"
    for persona in ("owner", "admin", "member"):
        resp = await scenario.client.patch(
            path, json={"name": f"r-{persona}"}, headers=_h(scenario.tokens[persona])
        )
        assert resp.status_code == 200, persona
    viewer = await scenario.client.patch(
        path, json={"name": "x"}, headers=_h(scenario.tokens["viewer"])
    )
    assert viewer.status_code == 403  # in-org but under-privileged
    outsider = await scenario.client.patch(
        path, json={"name": "x"}, headers=_h(scenario.tokens["outsider"])
    )
    assert outsider.status_code == 404


async def test_run_permission_viewer_denied_is_403(scenario: _Scenario) -> None:
    """owner/admin/member can run; an in-org viewer is 403; an outsider is 404."""
    path = f"/api/v1/projects/{scenario.project_id}/runs"
    for persona in ("owner", "admin", "member"):
        resp = await scenario.client.post(
            path, json=_RUN_BODY, headers=_h(scenario.tokens[persona])
        )
        assert resp.status_code == 202, persona
    viewer = await scenario.client.post(
        path, json=_RUN_BODY, headers=_h(scenario.tokens["viewer"])
    )
    assert viewer.status_code == 403
    outsider = await scenario.client.post(
        path, json=_RUN_BODY, headers=_h(scenario.tokens["outsider"])
    )
    assert outsider.status_code == 404


async def test_triage_permission(scenario: _Scenario) -> None:
    """member can triage a finding; viewer → 403; outsider → 404."""
    client = scenario.client
    run = await client.post(
        f"/api/v1/projects/{scenario.project_id}/runs",
        json=_RUN_BODY,
        headers=_h(scenario.tokens["owner"]),
    )
    job_id = run.json()["run_id"]
    findings = (
        await client.get(
            f"/api/v1/runs/{job_id}/findings", headers=_h(scenario.tokens["owner"])
        )
    ).json()
    assert findings["count"] >= 1
    path = f"/api/v1/runs/{job_id}/findings/{findings['findings'][0]['id']}"

    member = await client.patch(
        path, json={"status": "acknowledged"}, headers=_h(scenario.tokens["member"])
    )
    assert member.status_code == 200
    viewer = await client.patch(
        path, json={"status": "acknowledged"}, headers=_h(scenario.tokens["viewer"])
    )
    assert viewer.status_code == 403
    outsider = await client.patch(
        path, json={"status": "acknowledged"}, headers=_h(scenario.tokens["outsider"])
    )
    assert outsider.status_code == 404


async def test_nonmember_is_404_across_endpoints(scenario: _Scenario) -> None:
    """A non-member never gets a 403 on data endpoints — only 404 (leak-safe)."""
    out = _h(scenario.tokens["outsider"])
    pid = scenario.project_id
    cases = [
        ("GET", f"/api/v1/projects/{pid}", None),
        ("PATCH", f"/api/v1/projects/{pid}", {"name": "x"}),
        ("DELETE", f"/api/v1/projects/{pid}", None),
        ("GET", f"/api/v1/projects/{pid}/runs", None),
        ("GET", f"/api/v1/projects/{pid}/findings", None),
        ("POST", f"/api/v1/projects/{pid}/runs", _RUN_BODY),
    ]
    for method, path, body in cases:
        resp = await scenario.client.request(method, path, headers=out, json=body)
        assert resp.status_code == 404, (method, path, resp.status_code)
    # Org-level reads are leak-safe too.
    members = await scenario.client.get(
        f"/api/v1/orgs/{scenario.org_id}/members", headers=out
    )
    assert members.status_code == 404


async def test_create_project_in_org_requires_manage_project(
    scenario: _Scenario,
) -> None:
    """Creating into a named org needs MANAGE_PROJECT (viewer 403, outsider 404)."""
    body = {
        "name": "New",
        "repo_url": "https://git/new.git",
        "org_id": str(scenario.org_id),
    }
    member = await scenario.client.post(
        "/api/v1/projects", json=body, headers=_h(scenario.tokens["member"])
    )
    assert member.status_code == 201
    viewer = await scenario.client.post(
        "/api/v1/projects", json=body, headers=_h(scenario.tokens["viewer"])
    )
    assert viewer.status_code == 403
    outsider = await scenario.client.post(
        "/api/v1/projects", json=body, headers=_h(scenario.tokens["outsider"])
    )
    assert outsider.status_code == 404
