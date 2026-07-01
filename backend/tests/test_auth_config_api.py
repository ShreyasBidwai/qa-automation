"""Login-config endpoint (ADR-0056) — set/view/clear ``settings['auth_config']``.

The config is what ``resolve_target_auth_config`` reads to drive the authenticated
crawl. It carries no secret (the account/password/TOTP seed are in the vault); PUT +
DELETE are MANAGE_PROJECT, GET is VIEW. Only ``login_url`` + non-empty selector
overrides are stored (the AuthConfig defaults cover the rest).
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.repositories.project_repository import ProjectRepository


async def _create_project(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "AuthCfg", "repo_url": "https://git.example/x.git"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_auth_config_set_get_clear_roundtrip(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    project_id = await _create_project(client)
    base = f"/api/v1/projects/{project_id}/auth-config"

    # Unconfigured.
    assert (await client.get(base)).json()["configured"] is False

    # Set login_url + one selector override.
    resp = await client.put(
        base,
        json={"login_url": "https://app.test/login", "username_selector": "#email"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["login_url"] == "https://app.test/login"
    assert body["username_selector"] == "#email"
    assert body["password_selector"] is None  # not overridden

    # Persisted exactly as the resolver reads it — only non-empty values stored.
    async with app.state.sessionmaker() as session:
        project = await ProjectRepository(session).get(uuid.UUID(project_id))
    assert project is not None
    stored = project.settings["auth_config"]
    assert stored["login_url"] == "https://app.test/login"
    assert stored["username_selector"] == "#email"
    assert "password_selector" not in stored  # empty overrides are not persisted

    # GET reflects it; DELETE clears it; a second DELETE is 404.
    assert (await client.get(base)).json()["login_url"] == "https://app.test/login"
    assert (await client.delete(base)).status_code == 204
    assert (await client.get(base)).json()["configured"] is False
    assert (await client.delete(base)).status_code == 404


async def test_auth_config_requires_a_login_url(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _create_project(client)
    resp = await client.put(
        f"/api/v1/projects/{project_id}/auth-config",
        json={"username_selector": "#email"},  # no login_url
    )
    assert resp.status_code == 422


async def test_auth_config_never_accepts_a_secret_field(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    # Extra keys (e.g. a stray secret) are ignored by the schema — the stored config
    # only ever contains login_url + selectors.
    client, app = authed_client
    project_id = await _create_project(client)
    await client.put(
        f"/api/v1/projects/{project_id}/auth-config",
        json={"login_url": "https://app.test/login", "password": "should-be-ignored"},
    )
    async with app.state.sessionmaker() as session:
        project = await ProjectRepository(session).get(uuid.UUID(project_id))
    assert project is not None
    assert "password" not in project.settings["auth_config"]
    assert "should-be-ignored" not in str(project.settings["auth_config"])
