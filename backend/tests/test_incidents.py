"""Structured incident capture (dev-suite slice 1, ADR-0047).

Covers the fingerprint (groupable + deterministic), the provider phase-tagging
wrappers (tag + never swallow), the recorder (writes context; best-effort), the job
worker capture seam (phase from job kind or the inward tag; never breaks the run),
and the operator-gated read API. Incidents from the shared committing seams may
exist, so DB assertions scope by a fresh project id.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient

from app.incidents import (
    PHASE_PROVIDER,
    IncidentRecorder,
    capturing_ai_provider,
    capturing_embedding_provider,
    fingerprint,
    fingerprint_for,
    phase_of,
    tag_phase,
)
from app.models.enums import JobKind, JobStatus
from app.models.incident import Incident
from app.models.user import User
from app.repositories.incident_repository import IncidentRepository
from app.services.job_queue import ClaimedJob, JobQueue
from app.services.job_worker import JobWorker
from tests.factories import make_project


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- fingerprint: groupable + deterministic ----------------------------------


def _raise_value_error() -> None:
    raise ValueError("boom")


def test_same_failure_has_the_same_fingerprint() -> None:
    fingerprints: list[str] = []
    for _ in range(2):  # the identical failure, twice
        try:
            _raise_value_error()
        except ValueError as exc:
            fingerprints.append(fingerprint_for(exc))
    assert fingerprints[0] == fingerprints[1]  # groupable


def test_different_failures_have_different_fingerprints() -> None:
    try:
        raise ValueError("x")
    except ValueError as exc:
        a = fingerprint_for(exc)
    try:
        raise KeyError("x")
    except KeyError as exc:
        b = fingerprint_for(exc)
    assert a != b  # different exception type
    # Same type, different location → different fingerprint (location matters).
    assert fingerprint("ValueError", "a.py:f") != fingerprint("ValueError", "b.py:g")


def test_fingerprint_is_deterministic_16_hex() -> None:
    one = fingerprint("ValueError", "mod.py:fn")
    two = fingerprint("ValueError", "mod.py:fn")
    assert one == two and len(one) == 16


# --- provider wrappers: tag the phase, never swallow -------------------------


class _BoomAI:
    def generate(self, prompt: str, context: object, budget_tokens: int) -> str:
        raise RuntimeError("ai down")

    def triage(self, failure: object) -> object:
        raise RuntimeError("ai down")


class _OkAI:
    def generate(self, prompt: str, context: object, budget_tokens: int) -> str:
        return "code"

    def triage(self, failure: object) -> object:
        return None


def test_ai_wrapper_tags_provider_phase_and_reraises() -> None:
    wrapped = capturing_ai_provider(_BoomAI())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError) as excinfo:
        wrapped.generate("p", None, 10)  # type: ignore[arg-type]
    assert phase_of(excinfo.value, default="other") == PHASE_PROVIDER


def test_ai_wrapper_passes_success_through_unchanged() -> None:
    wrapped = capturing_ai_provider(_OkAI())  # type: ignore[arg-type]
    assert wrapped.generate("p", None, 10) == "code"  # type: ignore[arg-type]


class _BoomEmbed:
    dimension = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embed down")


def test_embedding_wrapper_tags_provider_phase() -> None:
    wrapped = capturing_embedding_provider(_BoomEmbed())  # type: ignore[arg-type]
    assert wrapped.dimension == 384
    with pytest.raises(RuntimeError) as excinfo:
        wrapped.embed(["x"])
    assert phase_of(excinfo.value, default="other") == PHASE_PROVIDER


# --- recorder: writes context; best-effort -----------------------------------


async def test_recorder_writes_an_incident_with_context(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    _, app = app_client
    recorder = IncidentRecorder(app.state.sessionmaker)
    project_id = uuid.uuid4()
    try:
        raise ValueError("kaboom")
    except ValueError as exc:
        await recorder.record(
            exc, phase="execution", project_id=project_id, component="unit"
        )

    async with app.state.sessionmaker() as session:
        rows = await IncidentRepository(session).list(
            project_id=project_id, limit=10, offset=0
        )
    assert len(rows) == 1
    incident = rows[0]
    assert incident.phase == "execution"
    assert incident.exception_type == "ValueError"
    assert incident.message == "kaboom"
    assert incident.traceback is not None and "ValueError" in incident.traceback
    assert incident.fingerprint and incident.component == "unit"


async def test_recorder_is_best_effort_when_the_write_fails(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    class _BrokenSessionmaker:
        def __call__(self) -> object:
            raise RuntimeError("incident db down")

    recorder = IncidentRecorder(_BrokenSessionmaker())  # type: ignore[arg-type]
    try:
        raise ValueError("x")
    except ValueError as exc:
        await recorder.record(exc, phase="job")  # must NOT raise


# --- worker capture seam -----------------------------------------------------


def _failing_handler(make_exc):  # type: ignore[no-untyped-def]
    async def handle(session, claimed: ClaimedJob):  # type: ignore[no-untyped-def]
        raise make_exc()

    return handle


async def _enqueue(app: FastAPI, kind: JobKind) -> tuple[uuid.UUID, uuid.UUID]:
    async with app.state.sessionmaker() as session:
        project = make_project()
        session.add(project)
        await session.flush()
        project_id = project.id
        job = await JobQueue(session).enqueue(kind=kind, project_id=project_id)
        job_id = job.id
        await session.commit()
    return job_id, project_id


async def _incidents_for(app: FastAPI, project_id: uuid.UUID) -> list[Incident]:
    async with app.state.sessionmaker() as session:
        return await IncidentRepository(session).list(
            project_id=project_id, limit=10, offset=0
        )


async def test_worker_records_execution_incident_for_a_run_job(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    _, app = app_client
    job_id, project_id = await _enqueue(app, JobKind.RUN)
    worker = JobWorker(
        app.state.sessionmaker,
        {JobKind.RUN: _failing_handler(lambda: RuntimeError("run boom"))},
        worker_id="t",
    )
    assert await worker.process_job(job_id) is True

    rows = await _incidents_for(app, project_id)
    assert len(rows) == 1
    assert rows[0].phase == "execution"  # mapped from the RUN job kind
    assert rows[0].exception_type == "RuntimeError"
    assert rows[0].project_id == project_id
    assert rows[0].component == "job:run"

    # Existing behaviour unchanged: the job is finalized (failed/retry), not stuck.
    async with app.state.sessionmaker() as session:
        job = await JobQueue(session).get(job_id)
    assert job is not None and job.status in (JobStatus.FAILED, JobStatus.QUEUED)


async def test_worker_records_ingest_incident_for_an_ingest_job(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    _, app = app_client
    job_id, project_id = await _enqueue(app, JobKind.INGEST)
    worker = JobWorker(
        app.state.sessionmaker,
        {JobKind.INGEST: _failing_handler(lambda: KeyError("missing"))},
        worker_id="t",
    )
    await worker.process_job(job_id)

    rows = await _incidents_for(app, project_id)
    assert len(rows) == 1 and rows[0].phase == "ingest"
    assert rows[0].exception_type == "KeyError"


async def test_worker_uses_the_inward_tagged_phase(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    _, app = app_client
    job_id, project_id = await _enqueue(app, JobKind.RUN)

    def make_provider_exc() -> RuntimeError:
        exc = RuntimeError("provider died")
        tag_phase(exc, PHASE_PROVIDER)  # tagged inward (as a provider call would)
        return exc

    worker = JobWorker(
        app.state.sessionmaker,
        {JobKind.RUN: _failing_handler(make_provider_exc)},
        worker_id="t",
    )
    await worker.process_job(job_id)

    rows = await _incidents_for(app, project_id)
    # The tag wins over the job-kind default → phase=provider, not execution.
    assert len(rows) == 1 and rows[0].phase == PHASE_PROVIDER


async def test_recording_failure_does_not_break_the_run(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    _, app = app_client
    job_id, project_id = await _enqueue(app, JobKind.RUN)

    class _BrokenSessionmaker:
        def __call__(self) -> object:
            raise RuntimeError("incident db down")

    worker = JobWorker(
        app.state.sessionmaker,
        {JobKind.RUN: _failing_handler(lambda: RuntimeError("boom"))},
        worker_id="t",
        incident_recorder=IncidentRecorder(_BrokenSessionmaker()),  # type: ignore[arg-type]
    )
    # Recording can't write, but the job still finalizes — capture is best-effort.
    assert await worker.process_job(job_id) is True
    async with app.state.sessionmaker() as session:
        job = await JobQueue(session).get(job_id)
    assert job is not None and job.status in (JobStatus.FAILED, JobStatus.QUEUED)
    assert await _incidents_for(app, project_id) == []  # nothing recorded, run survived


# --- operator-gated read API -------------------------------------------------


async def _signup(client: AsyncClient) -> tuple[str, uuid.UUID]:
    email = f"inc-{uuid.uuid4().hex[:12]}@example.test"
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "passw0rd1"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


@pytest_asyncio.fixture
async def operator(
    app_client: tuple[AsyncClient, FastAPI],
) -> tuple[AsyncClient, FastAPI, str]:
    client, app = app_client
    token, user_id = await _signup(client)
    async with app.state.sessionmaker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.is_operator = True
        await session.commit()
    return client, app, token


async def _seed_incident(app: FastAPI, **kwargs: object) -> uuid.UUID:
    async with app.state.sessionmaker() as session:
        incident = Incident(
            phase=kwargs.get("phase", "execution"),
            exception_type=kwargs.get("exception_type", "RuntimeError"),
            message=kwargs.get("message", "boom"),
            fingerprint=kwargs.get("fingerprint", "fp1234"),
            project_id=kwargs.get("project_id"),
            traceback=kwargs.get("traceback"),
        )
        session.add(incident)
        await session.flush()
        incident_id = incident.id
        await session.commit()
    return incident_id


async def test_non_operator_is_forbidden(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    token, _ = await _signup(client)  # an ordinary, non-operator user
    assert (await client.get("/api/v1/incidents", headers=_h(token))).status_code == 403
    bogus = uuid.uuid4()
    assert (
        await client.get(f"/api/v1/incidents/{bogus}", headers=_h(token))
    ).status_code == 403


async def test_operator_lists_and_reads_incidents(
    operator: tuple[AsyncClient, FastAPI, str],
) -> None:
    client, app, token = operator
    incident_id = await _seed_incident(app, traceback="Traceback...\nRuntimeError")

    listing = await client.get("/api/v1/incidents", headers=_h(token))
    assert listing.status_code == 200 and listing.json()["total"] >= 1

    detail = await client.get(f"/api/v1/incidents/{incident_id}", headers=_h(token))
    assert detail.status_code == 200
    body = detail.json()
    assert body["exception_type"] == "RuntimeError"
    assert body["traceback"] == "Traceback...\nRuntimeError"

    missing = await client.get(f"/api/v1/incidents/{uuid.uuid4()}", headers=_h(token))
    assert missing.status_code == 404


async def test_operator_can_filter_by_phase_and_project(
    operator: tuple[AsyncClient, FastAPI, str],
) -> None:
    client, app, token = operator
    project_id = uuid.uuid4()  # a fresh, unique project so the count is exact
    await _seed_incident(app, phase="execution", project_id=project_id, fingerprint="a")
    await _seed_incident(app, phase="ingest", project_id=project_id, fingerprint="b")

    resp = await client.get(
        f"/api/v1/incidents?project_id={project_id}&phase=ingest", headers=_h(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert all(item["phase"] == "ingest" for item in body["items"])
