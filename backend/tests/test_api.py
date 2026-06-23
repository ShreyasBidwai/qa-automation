"""HTTP API surface (T8.3) — fast tests with stubbed orchestrators/ingestion.

Drives the project + ingest + run + findings endpoints through the real app
(in-process, via the ASGI client + lifespan), with the RunExecutor / Ingestor
ports stubbed — no real generation, browser, or Docker. Background tasks complete
within the request under the ASGI transport, so polling is deterministic. A
separate test exercises the real OrchestratorRunExecutor wiring with stub
collaborators (Mode B path).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiConfigError
from app.api.execution import OrchestratorRunExecutor
from app.api.ports import RunExecution, RunRequest
from app.brain.cross_layer import Impact, Subgraph
from app.execution.types import (
    DbHandle,
    DbRole,
    ExecutionResult,
    PestScript,
    TargetEnv,
)
from app.models.enums import (
    FindingLayer,
    NodeKind,
    OracleSource,
    Outcome,
    RunMode,
)
from app.models.finding import Finding
from app.models.finding_result import FindingResult
from app.models.model_node import ModelNode
from app.models.organization import Organization
from app.models.project import Project
from app.modes.selection import SelectionStrategyKind, Target
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_result_repository import FindingResultRepository
from app.repositories.node_repository import NodeRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository
from tests.factories import make_node, make_result, make_run, make_test_case

_ENV = TargetEnv(
    app_path="/unused",
    execution_db=DbHandle("sqlite://:memory:", DbRole.WRITABLE_TEST, ephemeral=True),
    evidence_dir="/tmp/ev",
)


# --- stub ports --------------------------------------------------------------


class _StubExecutor:
    """Simulates an executed run: persists a run + one finding, or none (mode_c)."""

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, RunRequest]] = []

    async def execute(
        self, *, session: AsyncSession, project_id: uuid.UUID, request: RunRequest
    ) -> RunExecution:
        self.calls.append((project_id, request))
        if request.mode is RunMode.C:  # authoring → no run/findings
            return RunExecution(run_id=None, summary={"mode": "mode_c", "cases": 2})
        run = await RunRepository(session).add(make_run(project_id, status="failed"))
        expected = {"status": 500, "assertions": [{"kind": "status"}]}
        case = await TestCaseRepository(session).add(
            make_test_case(
                project_id,
                target_node=uuid.uuid4(),
                oracle_source=OracleSource.RULE_DERIVED,
                expected=expected,
            )
        )
        result = await ResultRepository(session).add(
            make_result(
                project_id,
                run.id,
                case.id,
                outcome=Outcome.FAIL,
                evidence_ref="ev/trace.zip",
            )
        )
        finding = await FindingRepository(session).add(
            Finding(
                project_id=project_id,
                run_id=run.id,
                result_id=result.id,
                root_cause_key="endpoint=GET api/x#fail|status=500",
                explains_count=1,
                title="api failure at GET api/x",
                layer=FindingLayer.API,
                oracle_source=OracleSource.RULE_DERIVED,
                confidence_mixed=False,
                expected=expected,
                location={"endpoints": ["GET api/x"], "tables": ["x_rows"]},
                severity="major",
                status="new",
            )
        )
        await FindingResultRepository(session).add(
            FindingResult(
                project_id=project_id, finding_id=finding.id, result_id=result.id
            )
        )
        return RunExecution(run_id=run.id, summary={"mode": "mode_b", "findings": 1})


class _StubIngestor:
    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    async def ingest(
        self, *, session: AsyncSession, project_id: uuid.UUID
    ) -> dict[str, object]:
        self.calls.append(project_id)
        return {"nodes": 0, "stub": True}


@pytest_asyncio.fixture
async def api(
    authed_client: tuple[AsyncClient, FastAPI],
) -> tuple[AsyncClient, _StubExecutor, _StubIngestor]:
    client, app = authed_client  # client already carries a signed-in user's token
    executor = _StubExecutor()
    ingestor = _StubIngestor()
    app.state.run_executor = executor
    app.state.ingestor = ingestor
    return client, executor, ingestor


async def _create_project(client: AsyncClient, name: str = "Demo") -> dict[str, object]:
    resp = await client.post(
        "/api/v1/projects",
        json={
            "name": name,
            "repo_url": "https://git.example/x.git",
            "app_url": "https://x.example",
            "auth_config_ref": "vault://x",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- projects ----------------------------------------------------------------


async def test_create_and_get_project(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    created = await _create_project(client, name="Checkout Service")
    assert created["name"] == "Checkout Service"
    assert created["repo_url"] == "https://git.example/x.git"
    assert str(created["slug"]).startswith("checkout-service-")

    got = await client.get(f"/api/v1/projects/{created['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]


async def test_get_unknown_project_is_404(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_create_project_validation_is_422(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    resp = await client.post("/api/v1/projects", json={"name": ""})  # missing repo_url
    assert resp.status_code == 422


# --- ingest ------------------------------------------------------------------


async def test_ingest_enqueues_background_job(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, ingestor = api
    project = await _create_project(client)

    resp = await client.post(f"/api/v1/projects/{project['id']}/ingest")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Background task ran under the ASGI transport.
    assert ingestor.calls == [uuid.UUID(str(project["id"]))]
    status = await client.get(f"/api/v1/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
    assert status.json()["kind"] == "ingest"


async def test_ingest_unknown_project_is_404(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    resp = await client.post(f"/api/v1/projects/{uuid.uuid4()}/ingest")
    assert resp.status_code == 404


# --- runs --------------------------------------------------------------------


async def test_run_mode_b_enqueues_and_creates_scoped_run(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, executor, _ = api
    project = await _create_project(client)

    resp = await client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"mode": "mode_b", "strategy": "full_sweep"},
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    assert executor.calls and executor.calls[0][0] == uuid.UUID(str(project["id"]))
    status = await client.get(f"/api/v1/runs/{run_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "succeeded"
    assert body["mode"] == "mode_b"
    assert body["summary"]["mode"] == "mode_b"
    # Enriched run-status payload (ADR-0048): the run row's number + timestamps are
    # surfaced (run_number is null here — the stub bypasses the assignment path).
    assert "run_number" in body
    assert body["created_at"] is not None


async def test_run_findings_shape(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"mode": "mode_b", "strategy": "full_sweep"},
    )
    run_id = resp.json()["run_id"]

    findings = await client.get(f"/api/v1/runs/{run_id}/findings")
    assert findings.status_code == 200
    body = findings.json()
    assert body["count"] == 1
    finding = body["findings"][0]
    assert finding["severity"] == "major"
    assert finding["status"] == "new"
    assert finding["oracle_source"] == "rule-derived"
    assert finding["layer"] == "api"
    assert finding["explains_count"] == 1
    assert finding["created_at"] is not None  # age/"when" for the drawer (ADR-0048)

    # widened detail the drawer renders ------------------------------------
    location = finding["location"]
    assert location["anchor"]["node_type"] == "table"  # deepest node wins
    assert location["anchor"]["identifier"] == "x_rows"
    assert location["endpoints"] == ["GET api/x"]
    assert location["tables"] == ["x_rows"]

    assert len(finding["evidence"]) == 1
    evidence = finding["evidence"][0]
    assert evidence["oracle_source"] == "rule-derived"  # the per-assertion trust
    assert evidence["summary"] == "Failed — expected status 500; checks status"
    assert evidence["reference"] == "ev/trace.zip"

    history = finding["history"]
    assert history["classification"] == "new"
    assert history["occurrence_count"] == 1
    assert finding["expected"] == {"status": 500, "assertions": [{"kind": "status"}]}

    # untriaged finding defaults to the open disposition (ADR-0027).
    assert finding["triage"] == {"status": "open", "note": None, "triaged_at": None}


async def test_triage_finding_persists_and_shows_on_get(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    run_id = (
        await client.post(
            f"/api/v1/projects/{project['id']}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )
    ).json()["run_id"]
    finding_id = (await client.get(f"/api/v1/runs/{run_id}/findings")).json()[
        "findings"
    ][0]["id"]

    patched = await client.patch(
        f"/api/v1/runs/{run_id}/findings/{finding_id}",
        json={"status": "acknowledged", "note": "owner is on it"},
    )
    assert patched.status_code == 200
    triage = patched.json()["triage"]
    assert triage["status"] == "acknowledged"
    assert triage["note"] == "owner is on it"
    assert triage["triaged_at"] is not None  # recorded; actor deferred to auth

    # The disposition is on the GET response too.
    again = (await client.get(f"/api/v1/runs/{run_id}/findings")).json()["findings"][0]
    assert again["triage"]["status"] == "acknowledged"


async def test_triage_bad_status_is_422(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    run_id = (
        await client.post(
            f"/api/v1/projects/{project['id']}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )
    ).json()["run_id"]
    finding_id = (await client.get(f"/api/v1/runs/{run_id}/findings")).json()[
        "findings"
    ][0]["id"]

    bad = await client.patch(
        f"/api/v1/runs/{run_id}/findings/{finding_id}",
        json={"status": "known"},  # collides with derived history → not a triage value
    )
    assert bad.status_code == 422


async def test_triage_missing_finding_is_404(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    run_id = (
        await client.post(
            f"/api/v1/projects/{project['id']}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )
    ).json()["run_id"]

    missing = await client.patch(
        f"/api/v1/runs/{run_id}/findings/{uuid.uuid4()}",
        json={"status": "resolved"},
    )
    assert missing.status_code == 404


async def test_triage_disposition_follows_the_issue_across_runs(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    """CRITICAL (ADR-0027): a finding triaged wont_fix in one run keeps that
    disposition in a LATER run producing the same root_cause_key — proving triage
    follows the logical issue, not the per-run finding row."""
    client, _, _ = api
    project = await _create_project(client)

    # Run 1 → finding with key X; mark it won't-fix.
    run1 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )
    ).json()["run_id"]
    finding1 = (await client.get(f"/api/v1/runs/{run1}/findings")).json()["findings"][0]
    await client.patch(
        f"/api/v1/runs/{run1}/findings/{finding1['id']}",
        json={"status": "wont_fix"},
    )

    # Run 2 (same project, same stub key X) → a DIFFERENT finding row.
    run2 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )
    ).json()["run_id"]
    finding2 = (await client.get(f"/api/v1/runs/{run2}/findings")).json()["findings"][0]

    assert finding2["id"] != finding1["id"]  # genuinely a later instance…
    assert finding2["root_cause_key"] == finding1["root_cause_key"]  # …same issue
    assert finding2["triage"]["status"] == "wont_fix"  # disposition carried over


async def test_run_mode_c_has_no_findings(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"mode": "mode_c", "prompt": "test the checkout flow"},
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    findings = await client.get(f"/api/v1/runs/{run_id}/findings")
    assert findings.status_code == 200
    assert findings.json() == {"run_id": run_id, "count": 0, "findings": []}


async def test_run_change_impact_requires_changeset_422(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"mode": "mode_b", "strategy": "change_impact"},  # no changeset
    )
    assert resp.status_code == 422


async def test_run_bad_mode_is_422(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"mode": "mode_x", "strategy": "full_sweep"},
    )
    assert resp.status_code == 422


async def test_run_unknown_project_is_404(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    resp = await client.post(
        f"/api/v1/projects/{uuid.uuid4()}/runs",
        json={"mode": "mode_b", "strategy": "full_sweep"},
    )
    assert resp.status_code == 404


async def test_unknown_run_is_404(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    assert (await client.get(f"/api/v1/runs/{uuid.uuid4()}")).status_code == 404
    assert (
        await client.get(f"/api/v1/runs/{uuid.uuid4()}/findings")
    ).status_code == 404


async def test_runs_and_findings_are_project_scoped(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project_a = await _create_project(client, name="A")
    project_b = await _create_project(client, name="B")

    run_a = (
        await client.post(
            f"/api/v1/projects/{project_a['id']}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )
    ).json()["run_id"]
    run_b = (
        await client.post(
            f"/api/v1/projects/{project_b['id']}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )
    ).json()["run_id"]

    findings_a = (await client.get(f"/api/v1/runs/{run_a}/findings")).json()
    findings_b = (await client.get(f"/api/v1/runs/{run_b}/findings")).json()
    # Each run sees exactly its own finding — no cross-project bleed.
    assert findings_a["count"] == 1 and findings_b["count"] == 1
    assert findings_a["findings"][0]["id"] != findings_b["findings"][0]["id"]


async def test_slim_backend_enqueues_run_without_a_local_executor(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    """B5 (ADR-0036): the toolchain-free control plane still enqueues a run — it is
    not dispatched in-process (no executor), it stays queued for a runner worker."""
    client, _ = authed_client  # no api fixture → run_executor stays None
    project = await _create_project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"mode": "mode_b", "strategy": "full_sweep"},
    )
    assert resp.status_code == 202
    job_id = resp.json()["run_id"]
    # No local executor ran it → it is durably queued, awaiting a worker.
    status = await client.get(f"/api/v1/runs/{job_id}")
    assert status.json()["status"] == "queued"


async def test_slim_backend_enqueues_ingest_without_a_local_ingestor(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project = await _create_project(client)
    resp = await client.post(f"/api/v1/projects/{project['id']}/ingest")
    assert resp.status_code == 202
    status = await client.get(f"/api/v1/jobs/{resp.json()['job_id']}")
    assert status.json()["status"] == "queued"


class _Failing:
    """A port whose work raises — exercises the background failure path."""

    async def execute(
        self, *, session: AsyncSession, project_id: uuid.UUID, request: RunRequest
    ) -> RunExecution:
        raise RuntimeError("boom")

    async def ingest(
        self, *, session: AsyncSession, project_id: uuid.UUID
    ) -> dict[str, object]:
        raise RuntimeError("boom")


async def test_run_job_records_failure(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    app.state.run_executor = _Failing()
    project = await _create_project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"mode": "mode_b", "strategy": "full_sweep"},
    )
    assert resp.status_code == 202
    status = await client.get(f"/api/v1/runs/{resp.json()['run_id']}")
    assert status.json()["status"] == "failed"


async def test_ingest_job_records_failure(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    app.state.ingestor = _Failing()
    project = await _create_project(client)
    resp = await client.post(f"/api/v1/projects/{project['id']}/ingest")
    assert resp.status_code == 202
    status = await client.get(f"/api/v1/jobs/{resp.json()['job_id']}")
    assert status.json()["status"] == "failed"
    assert status.json()["detail"] == "RuntimeError"


async def _run_and_finding(
    client: AsyncClient, project_id: str
) -> tuple[str, dict[str, object]]:
    """Trigger a stub mode_b run and return (run_id, its one finding)."""
    rid = (
        await client.post(
            f"/api/v1/projects/{project_id}/runs",
            json={"mode": "mode_b", "strategy": "full_sweep"},
        )
    ).json()["run_id"]
    finding = (await client.get(f"/api/v1/runs/{rid}/findings")).json()["findings"][0]
    return rid, finding


# --- open-findings inbox (ADR-0028) -----------------------------------------


async def test_open_findings_inbox_lists_then_excludes_muted(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    pid = project["id"]
    run_id, finding = await _run_and_finding(client, str(pid))
    fid = finding["id"]

    # Per-project inbox (scoped → exact): one open finding, full shape + ids.
    scoped = await client.get(f"/api/v1/projects/{pid}/findings")
    assert scoped.status_code == 200
    body = scoped.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == fid
    assert item["project_id"] == pid
    assert item["run_id"] == finding["run_id"]
    assert item["triage"]["status"] == "open"
    assert "evidence" in item and "history" in item and "location" in item

    # Global inbox (cross-project → membership): our finding is present.
    glob = await client.get("/api/v1/findings")
    assert glob.status_code == 200
    assert fid in {i["id"] for i in glob.json()["items"]}

    # Mute it → it leaves both inboxes.
    patched = await client.patch(
        f"/api/v1/runs/{run_id}/findings/{fid}", json={"status": "wont_fix"}
    )
    assert patched.status_code == 200
    assert (await client.get(f"/api/v1/projects/{pid}/findings")).json()["total"] == 0
    assert fid not in {
        i["id"] for i in (await client.get("/api/v1/findings")).json()["items"]
    }


async def test_project_open_findings_unknown_project_is_404(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}/findings")
    assert resp.status_code == 404


# --- bulk triage -------------------------------------------------------------


async def test_bulk_triage_multi_set_and_partial_failure(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    pid = str(project["id"])
    _, f1 = await _run_and_finding(client, pid)
    _, f2 = await _run_and_finding(client, pid)  # a later run, same root_cause_key
    bogus = str(uuid.uuid4())

    resp = await client.post(
        "/api/v1/findings/triage",
        json={"finding_ids": [f1["id"], f2["id"], bogus], "status": "wont_fix"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "wont_fix"
    assert body["requested"] == 3
    assert set(body["updated"]) == {f1["id"], f2["id"]}  # both real ids triaged
    assert body["not_found"] == [bogus]  # partial failure reported, not fatal

    # The (now muted) issue is gone from the project inbox.
    assert (await client.get(f"/api/v1/projects/{pid}/findings")).json()["total"] == 0


async def test_bulk_triage_bad_status_is_422(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    resp = await client.post(
        "/api/v1/findings/triage",
        json={"finding_ids": [str(uuid.uuid4())], "status": "known"},
    )
    assert resp.status_code == 422


# --- project CRUD (PATCH / DELETE) ------------------------------------------


async def test_patch_project_updates_fields_and_app_url_round_trips(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    pid = project["id"]

    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"name": "Renamed", "app_url": "https://new.example", "stack": "laravel"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["app_url"] == "https://new.example"
    assert body["stack"] == "laravel"
    # repo_url (untouched) is preserved.
    assert body["repo_url"] == "https://git.example/x.git"

    got = (await client.get(f"/api/v1/projects/{pid}")).json()
    assert got["app_url"] == "https://new.example"
    assert got["name"] == "Renamed"
    assert got["stack"] == "laravel"


async def test_patch_unknown_project_is_404(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    resp = await client.patch(f"/api/v1/projects/{uuid.uuid4()}", json={"name": "X"})
    assert resp.status_code == 404


async def test_patch_project_validation_is_422(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    resp = await client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": ""}  # min_length=1
    )
    assert resp.status_code == 422


async def test_delete_project_soft_deletes(
    api: tuple[AsyncClient, _StubExecutor, _StubIngestor],
) -> None:
    client, _, _ = api
    project = await _create_project(client)
    pid = project["id"]

    deleted = await client.delete(f"/api/v1/projects/{pid}")
    assert deleted.status_code == 204
    # Hidden from reads (get + the project inbox) and idempotent.
    assert (await client.get(f"/api/v1/projects/{pid}")).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/findings")).status_code == 404
    assert (await client.delete(f"/api/v1/projects/{pid}")).status_code == 404


# --- auth enforcement + project ownership (B2, ADR-0031) --------------------


def _email() -> str:
    return f"u-{uuid.uuid4().hex[:12]}@example.test"


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": _email(), "password": "ownerpw123"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def test_protected_endpoints_reject_unauthenticated(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client  # raw client — no token
    assert (await client.get("/api/v1/projects")).status_code == 401
    create = await client.post(
        "/api/v1/projects", json={"name": "x", "repo_url": "https://git/x.git"}
    )
    assert create.status_code == 401
    assert (await client.get("/api/v1/findings")).status_code == 401


async def test_project_ownership_is_enforced(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    owner = await _signup(client)
    other = await _signup(client)
    pid = (
        await client.post(
            "/api/v1/projects",
            json={"name": "Owned", "repo_url": "https://git/x.git"},
            headers=_hdr(owner),
        )
    ).json()["id"]

    # The owner can access it.
    owner_get = await client.get(f"/api/v1/projects/{pid}", headers=_hdr(owner))
    assert owner_get.status_code == 200

    # A different user cannot — 404 (not 403; existence is not leaked).
    for method, path in [
        ("GET", f"/api/v1/projects/{pid}"),
        ("GET", f"/api/v1/projects/{pid}/runs"),
        ("GET", f"/api/v1/projects/{pid}/findings"),
        ("DELETE", f"/api/v1/projects/{pid}"),
    ]:
        resp = await client.request(method, path, headers=_hdr(other))
        assert resp.status_code == 404, (method, path)
    patched = await client.patch(
        f"/api/v1/projects/{pid}", json={"name": "hijack"}, headers=_hdr(other)
    )
    assert patched.status_code == 404


async def test_project_in_foreign_org_is_404(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    """Org tenancy (ADR-0032/0033): a project in an org the caller does NOT belong
    to is 404 — existence is not leaked. (The legacy NULL-owner → Legacy-org
    migration is covered in test_org_migration.py.)"""
    client, app = authed_client
    async with app.state.sessionmaker() as session:
        org = Organization(name="Foreign", is_personal=False)
        session.add(org)
        await session.flush()
        project = Project(
            name="Foreign",
            slug=f"foreign-{uuid.uuid4().hex[:8]}",
            org_id=org.id,
            settings={"repo_url": "https://git/foreign.git"},
        )
        session.add(project)
        await session.flush()
        project_id = project.id
        await session.commit()
    got = await client.get(f"/api/v1/projects/{project_id}")
    assert got.status_code == 404  # not a member of the project's org → leak-safe


# --- the real OrchestratorRunExecutor wiring (stub collaborators) ------------


class _FakeResolver:
    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        node = ModelNode(
            project_id=project_id, kind=NodeKind.ENDPOINT, name="ep", attributes={}
        )
        return Subgraph(root=node, nodes=(node,), edges=())

    async def impact(self, project_id: uuid.UUID, node_id: uuid.UUID) -> Impact:
        node = ModelNode(
            project_id=project_id, kind=NodeKind.ENDPOINT, name="ep", attributes={}
        )
        return Impact(node=node, callers=(), writes=(), roles=(), edges=())


class _StubGenerator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def generate(self, *, project_id: uuid.UUID, target: Target) -> PestScript:
        case = await TestCaseRepository(self._session).add(
            make_test_case(project_id, target_node=target.node_id)
        )
        from tests.factories import make_test_script

        script = await TestScriptRepository(self._session).add(
            make_test_script(project_id, case.id)
        )
        return PestScript(
            test_case_id=case.id, script_id=script.id, name="gen", code=script.code
        )


class _StubRunner:
    framework = "stub"

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]:
        return [
            ExecutionResult(
                test_case_id=s.test_case_id,
                script_id=s.script_id,
                name=s.name,
                outcome=Outcome.FAIL,
                evidence_ref="ev",
            )
            for s in scripts
        ]

    def teardown(self, target_env: TargetEnv) -> None:
        return None


async def test_orchestrator_executor_runs_mode_b(db_session: AsyncSession) -> None:
    from app.models.project import Project
    from app.repositories.project_repository import ProjectRepository

    project = await ProjectRepository(db_session).add(
        Project(name="Wired", slug=f"wired-{uuid.uuid4().hex[:8]}", settings={})
    )
    await NodeRepository(db_session).add(
        make_node(project.id, kind=NodeKind.ENDPOINT, name="GET /x")
    )

    executor = OrchestratorRunExecutor(
        runner=_StubRunner(),
        target_env=_ENV,
        resolver_factory=lambda _session: _FakeResolver(),
        target_generator_factory=lambda session: _StubGenerator(session),
    )
    execution = await executor.execute(
        session=db_session,
        project_id=project.id,
        request=RunRequest(
            mode=RunMode.B, strategy=SelectionStrategyKind.FULL_SWEEP, max_targets=50
        ),
    )

    assert execution.run_id is not None
    assert execution.summary["mode"] == "mode_b"
    assert execution.summary["findings"] >= 1


async def test_orchestrator_executor_mode_c_unconfigured_raises(
    db_session: AsyncSession,
) -> None:
    executor = OrchestratorRunExecutor(
        runner=_StubRunner(),
        target_env=_ENV,
        resolver_factory=lambda _session: _FakeResolver(),
        target_generator_factory=lambda session: _StubGenerator(session),
    )  # no AI/embedding providers
    with pytest.raises(ApiConfigError):
        await executor.execute(
            session=db_session,
            project_id=uuid.uuid4(),
            request=RunRequest(mode=RunMode.C, prompt="hi"),
        )
