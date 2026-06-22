"""DB-state tier API + RBAC (B10, ADR-0043).

Default off; settable by MANAGE_PROJECT; readable by VIEW; a viewer can read but not
change it (403); a non-member is 404; a bad value is 422.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client: AsyncClient) -> tuple[str, uuid.UUID]:
    email = f"dbs-{uuid.uuid4().hex[:12]}@example.test"
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "passw0rd1"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


async def test_default_off_then_set_and_read_back(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    token, _ = await _signup(client)
    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"name": "P", "repo_url": "https://git/p.git"},
            headers=_h(token),
        )
    ).json()["id"]
    base = f"/api/v1/projects/{project_id}/db-state-tier"

    assert (await client.get(base, headers=_h(token))).json()["tier"] == "off"
    put = await client.put(base, json={"tier": "full"}, headers=_h(token))
    assert put.status_code == 200 and put.json()["tier"] == "full"
    assert (await client.get(base, headers=_h(token))).json()["tier"] == "full"


async def test_bad_tier_is_422(app_client: tuple[AsyncClient, FastAPI]) -> None:
    client, _ = app_client
    token, _ = await _signup(client)
    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"name": "P", "repo_url": "https://git/p.git"},
            headers=_h(token),
        )
    ).json()["id"]
    resp = await client.put(
        f"/api/v1/projects/{project_id}/db-state-tier",
        json={"tier": "everything"},  # not a valid tier
        headers=_h(token),
    )
    assert resp.status_code == 422


async def test_tier_change_is_rbac_gated(
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
        await session.commit()

    base = f"/api/v1/projects/{project_id}/db-state-tier"
    body = {"tier": "read_only"}

    # owner (MANAGE_PROJECT) can change the tier.
    assert (await client.put(base, json=body, headers=_h(owner))).status_code == 200
    # viewer can read but NOT change (403).
    assert (await client.get(base, headers=_h(viewer))).status_code == 200
    assert (await client.put(base, json=body, headers=_h(viewer))).status_code == 403
    # a non-member is 404 (existence not leaked).
    assert (await client.get(base, headers=_h(outsider))).status_code == 404
    assert (await client.put(base, json=body, headers=_h(outsider))).status_code == 404
