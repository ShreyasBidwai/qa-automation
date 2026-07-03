"""The CSV import endpoint (POST /projects/{id}/tests/import) — MANAGE_PROJECT.

End-to-end: a multipart CSV upload becomes persisted, runnable test cases that then
show up in the read-only Tests viewer. Covers the happy path, a partial file (good
rows land, bad rows report), idempotent re-import, and RBAC/validation guards.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

_CSV = (
    "name,method,path,expected_status,payload,authenticated\n"
    "List orders,GET,api/v1/orders,200,,true\n"
    'Create order,POST,api/v1/orders,201,"{""qty"": 2}",true\n'
)


async def _new_project(client: AsyncClient) -> uuid.UUID:
    resp = await client.post("/api/v1/projects", json={"name": "T", "repo_url": "/r"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _upload(csv: str) -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("tests.csv", csv.encode("utf-8"), "text/csv")}


async def test_import_persists_runnable_tests_visible_in_the_viewer(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/tests/import", files=_upload(_CSV)
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary == {"total": 2, "created": 2, "updated": 0, "errors": []}

    # The imported scenarios are now first-class cases in the Tests viewer, with
    # runnable code carrying exactly the request the QA declared.
    listing = (await client.get(f"/api/v1/projects/{project_id}/tests")).json()
    assert listing["total"] == 2
    codes = "\n".join(item["code"] for item in listing["items"])
    assert "$this->postJson('api/v1/orders', ['qty' => 2])" in codes
    assert "assertStatus(201)" in codes
    assert all(item["oracle_source"] == "spec-grounded" for item in listing["items"])


async def test_reimport_updates_in_place_not_duplicates(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    base = f"/api/v1/projects/{project_id}/tests/import"

    first = (await client.post(base, files=_upload(_CSV))).json()
    assert first["created"] == 2
    second = (await client.post(base, files=_upload(_CSV))).json()
    # Same scenarios → updated in place, never a second copy.
    assert second == {"total": 2, "created": 0, "updated": 2, "errors": []}
    listing = (await client.get(f"/api/v1/projects/{project_id}/tests")).json()
    assert listing["total"] == 2


async def test_partial_file_lands_good_rows_and_reports_bad(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    csv = (
        "method,path,expected_status\n"
        "GET,api/ok,200\n"
        "NOPE,api/bad,200\n"  # invalid method → reported, not persisted
    )
    resp = await client.post(
        f"/api/v1/projects/{project_id}/tests/import", files=_upload(csv)
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["total"] == 1 and summary["created"] == 1
    assert summary["errors"][0]["row"] == 2
    assert "method" in summary["errors"][0]["message"]


async def test_all_bad_rows_persist_nothing_but_report(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    csv = "method,path,expected_status\nNOPE,api/bad,999\n"
    summary = (
        await client.post(
            f"/api/v1/projects/{project_id}/tests/import", files=_upload(csv)
        )
    ).json()
    assert summary["total"] == 0 and summary["created"] == 0
    assert summary["errors"]
    assert (await client.get(f"/api/v1/projects/{project_id}/tests")).json()[
        "total"
    ] == 0


async def test_empty_and_non_utf8_uploads_are_rejected(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    base = f"/api/v1/projects/{project_id}/tests/import"

    empty = await client.post(base, files={"file": ("e.csv", b"   \n", "text/csv")})
    assert empty.status_code == 400

    binary = await client.post(
        base, files={"file": ("b.csv", b"\xff\xfe\x00", "text/csv")}
    )
    assert binary.status_code == 400


async def test_import_is_manage_gated_no_leak_to_outsiders(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    # A non-member cannot import into (or even confirm the existence of) a project.
    client, _ = authed_client
    project_id = await _new_project(client)
    outsider = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": f"o-{uuid.uuid4().hex[:8]}@e.test", "password": "passw0rd1"},
        )
    ).json()["access_token"]
    resp = await client.post(
        f"/api/v1/projects/{project_id}/tests/import",
        files=_upload(_CSV),
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 404
