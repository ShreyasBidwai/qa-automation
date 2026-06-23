"""Run layer scope + document upload + two finding-endpoint follow-ups (ADR-0052).

Item 1: the layer filter is honored by planning (unit + orchestrator + API validation
+ payload round-trip). Item 2: file upload stores+embeds+lists, RBAC-gated, and a
failing embed leaves the project untouched (best-effort). Item 3: GET /findings/{id}
returns the full payload, auth 404/200. Item 4: the /findings project_id filter
narrows the FULL result set server-side; omitted is unchanged. Hermetic — stub
executor + stub embedder, no real browser/model.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.composition import StubRunExecutor
from app.api.ports import (
    run_request_from_payload,
    run_request_to_payload,
    to_run_request,
)
from app.api.schemas import ModeBRunRequest
from app.embeddings.errors import EmbeddingProviderError
from app.embeddings.stub import StubEmbeddingProvider
from app.embeddings.types import Vector
from app.models.enums import FindingLayer, NodeKind, OracleSource, Outcome
from app.models.finding import Finding
from app.models.organization import Organization
from app.modes.mode_b import ModeBBounds, ModeBOrchestrator
from app.modes.selection import (
    SelectionStrategyKind,
    Target,
    build_selection_strategy,
    targets_for_layers,
)
from app.repositories.organization_repository import OrganizationRepository
from tests.factories import make_project, make_run, make_result, make_test_case
from tests.test_mode_b import (
    _ENV,
    _FakeResolver,
    _node,
    _project,
    _StubGenerator,
    _StubRunner,
)

_PROJECT_BODY = {"name": "Cfg", "repo_url": "https://git.example/x.git"}


async def _create_project(client: AsyncClient, name: str = "Cfg") -> str:
    resp = await client.post(
        "/api/v1/projects", json={**_PROJECT_BODY, "name": name}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _personal_org_id(client: AsyncClient) -> uuid.UUID:
    body = (await client.get("/api/v1/orgs")).json()
    for org in body["items"]:
        if org["is_personal"]:
            return uuid.UUID(org["id"])
    raise AssertionError("authed user has no personal org")


# --- item 1: layer scope -----------------------------------------------------


def test_targets_for_layers_filters_by_kind() -> None:
    page = Target(node_id=uuid.uuid4(), kind=NodeKind.PAGE, name="/p")
    endpoint = Target(node_id=uuid.uuid4(), kind=NodeKind.ENDPOINT, name="GET /e")
    targets = (page, endpoint)
    assert targets_for_layers(targets, None) == targets  # full = unchanged
    assert targets_for_layers(targets, frozenset({"ui"})) == (page,)
    assert targets_for_layers(targets, frozenset({"api"})) == (endpoint,)
    assert targets_for_layers(targets, frozenset({"ui", "api"})) == targets
    assert targets_for_layers(targets, frozenset({"db"})) == ()  # no target kind


def test_mode_b_request_layers_validation() -> None:
    request = ModeBRunRequest(
        mode="mode_b", strategy="full_sweep", layers=["api", "ui", "api"]
    )
    assert request.layers == ["api", "ui"]  # deduped + deterministically ordered
    assert ModeBRunRequest(mode="mode_b", strategy="full_sweep").layers is None
    with pytest.raises(ValidationError):
        ModeBRunRequest(mode="mode_b", strategy="full_sweep", layers=[])
    with pytest.raises(ValidationError):
        ModeBRunRequest(mode="mode_b", strategy="full_sweep", layers=["bogus"])


def test_run_request_round_trip_preserves_layers() -> None:
    request = to_run_request(
        ModeBRunRequest(mode="mode_b", strategy="full_sweep", layers=["api", "ui"])
    )
    assert request.layers == frozenset({"api", "ui"})
    payload = run_request_to_payload(request)
    assert payload["layers"] == ["api", "ui"]  # sorted for the durable payload
    assert run_request_from_payload(payload).layers == frozenset({"api", "ui"})

    # Omitted survives the whole round-trip as None (existing behaviour).
    plain = to_run_request(ModeBRunRequest(mode="mode_b", strategy="full_sweep"))
    assert plain.layers is None
    assert run_request_from_payload(run_request_to_payload(plain)).layers is None


async def test_mode_b_layer_scope_drives_only_that_layer(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    endpoint = await _node(db_session, project_id, NodeKind.ENDPOINT, "GET api/orders")
    page = await _node(db_session, project_id, NodeKind.PAGE, "/orders")

    generator = _StubGenerator(db_session)
    orchestrator = ModeBOrchestrator(
        session=db_session,
        runner=_StubRunner(Outcome.FAIL),
        target_env=_ENV,
        resolver=_FakeResolver(),
        generator=generator,
    )
    strategy = build_selection_strategy(
        SelectionStrategyKind.FULL_SWEEP, session=db_session
    )
    report = await orchestrator.run(
        project_id=project_id,
        strategy=strategy,
        bounds=ModeBBounds(max_targets=10, layers=frozenset({"api"})),
    )

    # Only the endpoint (api) target was driven; the page (ui) was filtered out.
    assert generator.generated_for == [endpoint.id]
    assert page.id not in generator.generated_for
    assert report.targets_selected == 1


async def test_run_create_accepts_and_validates_layers(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _create_project(client)
    base = f"/api/v1/projects/{project_id}/runs"

    ok = await client.post(
        base, json={"mode": "mode_b", "strategy": "full_sweep", "layers": ["api", "ui"]}
    )
    assert ok.status_code == 202
    bad = await client.post(
        base, json={"mode": "mode_b", "strategy": "full_sweep", "layers": ["bogus"]}
    )
    assert bad.status_code == 422
    empty = await client.post(
        base, json={"mode": "mode_b", "strategy": "full_sweep", "layers": []}
    )
    assert empty.status_code == 422


# --- item 2: document upload -------------------------------------------------


class _FailingEmbedder:
    dimension = 384

    def embed(self, texts: list[str]) -> list[Vector]:
        raise EmbeddingProviderError("embedding backend is down")


@pytest_asyncio.fixture
async def docs_client(
    authed_client: tuple[AsyncClient, FastAPI],
) -> tuple[AsyncClient, FastAPI]:
    client, app = authed_client
    app.state.embedding_provider = StubEmbeddingProvider()
    return client, app


async def test_document_upload_stores_embeds_and_lists(
    docs_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = docs_client
    project_id = await _create_project(client, "Up")
    base = f"/api/v1/projects/{project_id}/documents"

    resp = await client.post(
        f"{base}/upload",
        files={"file": ("spec.txt", b"Para one.\n\nPara two here.", "text/plain")},
        data={"doc_kind": "requirements", "title": "Spec"},
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["title"] == "Spec" and doc["doc_kind"] == "requirements"
    assert doc["chunk_count"] >= 1  # the B9 pipeline chunked + embedded it

    listing = (await client.get(base)).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == doc["id"]


async def test_document_upload_falls_back_to_filename_and_rejects_non_utf8(
    docs_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = docs_client
    project_id = await _create_project(client, "Up2")
    base = f"/api/v1/projects/{project_id}/documents/upload"

    named = await client.post(
        base, files={"file": ("requirements.md", b"content here", "text/markdown")}
    )
    assert named.status_code == 201
    assert named.json()["title"] == "requirements.md"  # filename when no title

    binary = await client.post(
        base, files={"file": ("b.dat", b"\xff\xfe\x00x", "application/octet-stream")}
    )
    assert binary.status_code == 400  # not UTF-8 text

    empty = await client.post(base, files={"file": ("e.txt", b"   \n  ", "text/plain")})
    assert empty.status_code == 400  # empty after strip

    bad_kind = await client.post(
        base,
        files={"file": ("x.txt", b"text", "text/plain")},
        data={"doc_kind": "nonsense"},
    )
    assert bad_kind.status_code == 422  # unknown doc_kind


async def test_document_upload_embed_failure_does_not_corrupt_project(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    app.state.embedding_provider = _FailingEmbedder()
    project_id = await _create_project(client, "Up3")
    base = f"/api/v1/projects/{project_id}/documents"

    resp = await client.post(
        f"{base}/upload", files={"file": ("x.txt", b"some text", "text/plain")}
    )
    assert resp.status_code == 502  # best-effort: clean error, not a raw 500
    # The project is untouched — the failed embed rolled back, no orphan document.
    assert (await client.get(base)).json()["total"] == 0


async def test_document_upload_is_rbac_gated_to_members(
    docs_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = docs_client
    project_id = await _create_project(client, "Up4")
    # A different user (not in the project's org) cannot upload → 404 (not leaked).
    outsider = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": f"o-{uuid.uuid4().hex[:8]}@e.test", "password": "passw0rd1"},
        )
    ).json()["access_token"]
    resp = await client.post(
        f"/api/v1/projects/{project_id}/documents/upload",
        files={"file": ("x.txt", b"text", "text/plain")},
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 404


# --- item 3: GET /findings/{id} ---------------------------------------------


async def _seed_finding(
    app: FastAPI, *, org_id: uuid.UUID, screenshot_ref: str | None = None
) -> uuid.UUID:
    """Commit a minimal project + run + result + finding in ``org_id``."""
    async with app.state.sessionmaker() as session:
        project = make_project(org_id=org_id)
        session.add(project)
        await session.flush()
        run = make_run(project.id)
        session.add(run)
        await session.flush()
        case = make_test_case(project.id)
        session.add(case)
        await session.flush()
        result = make_result(project.id, run.id, case.id, outcome=Outcome.FAIL)
        session.add(result)
        await session.flush()
        finding = Finding(
            project_id=project.id,
            run_id=run.id,
            result_id=result.id,
            root_cause_key=f"k-{uuid.uuid4().hex[:10]}",
            explains_count=1,
            title="api failure",
            layer=FindingLayer.API,
            oracle_source=OracleSource.RULE_DERIVED,
            confidence_mixed=False,
            expected={},
            location={},
            severity="major",
            status="new",
            screenshot_ref=screenshot_ref,
        )
        session.add(finding)
        await session.flush()
        finding_id = finding.id
        await session.commit()
    return finding_id


async def _excluded_org(app: FastAPI) -> uuid.UUID:
    async with app.state.sessionmaker() as session:
        org = await OrganizationRepository(session).add(
            Organization(name="Other", is_personal=False)
        )
        org_id = org.id
        await session.commit()
    return org_id


async def test_get_finding_returns_full_payload(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    app.state.run_executor = StubRunExecutor()
    project_id = await _create_project(client, "Find")
    run = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"mode": "mode_b", "strategy": "full_sweep"},
    )
    job_id = run.json()["run_id"]
    listed = (await client.get(f"/api/v1/runs/{job_id}/findings")).json()["findings"]
    finding_id = listed[0]["id"]

    resp = await client.get(f"/api/v1/findings/{finding_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == finding_id
    assert body["has_screenshot"] is True  # the stub attaches a placeholder
    assert body["title"] and body["triage"]["status"] == "open"
    assert "location" in body and "evidence" in body and "history" in body


async def test_get_finding_404_for_unknown_or_inaccessible(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    assert (await client.get(f"/api/v1/findings/{uuid.uuid4()}")).status_code == 404
    # A finding in an org the caller can't view → 404 (existence not leaked).
    other = await _seed_finding(app, org_id=await _excluded_org(app))
    assert (await client.get(f"/api/v1/findings/{other}")).status_code == 404


# --- item 4: server-side project filter on /findings ------------------------


async def test_findings_project_filter_narrows_the_full_result_set(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    app.state.run_executor = StubRunExecutor()
    project_a = await _create_project(client, "A")
    project_b = await _create_project(client, "B")
    for pid in (project_a, project_b):
        await client.post(
            f"/api/v1/projects/{pid}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )

    # The global inbox spans both projects.
    everything = (await client.get("/api/v1/findings")).json()
    assert everything["total"] == 2

    # project_id narrows the FULL set + total server-side — not just the page.
    only_a = (await client.get(f"/api/v1/findings?project_id={project_a}")).json()
    assert only_a["total"] == 1
    assert all(item["project_id"] == project_a for item in only_a["items"])

    # Omitted is unchanged.
    assert (await client.get("/api/v1/findings")).json()["total"] == 2
