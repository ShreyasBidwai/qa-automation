"""Failure screenshots — capture, store behind one indirection, serve authorized (ADR-0051).

The storage round-trip + opaque-ref/path-traversal safety; capture at the execution
seam (failing result attaches a ref, passing attaches none, a store failure can't
break the run); the assembler propagating the ref to the finding; ``has_screenshot``
on the payload; and the authorized ``GET /findings/{id}/screenshot`` (streams bytes /
404s). Hermetic — the stub placeholder, no real browser; storage is pointed at a tmp
dir via the single indirection's settings hook.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import boto3
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.composition import StubRunExecutor
from app.execution.lifecycle import STATUS_FAILED, RunLifecycle
from app.execution.types import (
    DbHandle,
    DbRole,
    ExecutionResult,
    TargetEnv,
)
from app.models.enums import (
    FindingLayer,
    OracleSource,
    Outcome,
    RunMode,
    RunTrigger,
)
from app.models.finding import Finding
from app.models.organization import Organization
from app.reporting.finding_assembler import FindingAssembler
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.screenshots import (
    get_screenshot,
    placeholder_screenshot,
    store_project_screenshot,
    store_screenshot,
)
from app.screenshots import storage as screenshot_storage
from tests.factories import make_project, make_result, make_run, make_test_case


@pytest.fixture
def shot_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the storage indirection's default dir at a tmp path (for default-path
    store/get calls in the lifecycle, the stub, and the endpoint)."""
    directory = tmp_path / "shots"
    monkeypatch.setattr(
        screenshot_storage,
        "get_settings",
        lambda: SimpleNamespace(screenshot_dir=str(directory)),
    )
    return directory


# --- storage: round-trip, opaque ref, traversal-safe -------------------------


def test_store_returns_opaque_ref_and_get_round_trips(tmp_path) -> None:
    ref = store_screenshot(b"image-bytes", base_dir=tmp_path)
    # The ref is an opaque key, never a path.
    assert len(ref) == 32 and all(c in "0123456789abcdef" for c in ref)
    assert "/" not in ref and "." not in ref
    assert get_screenshot(ref, base_dir=tmp_path) == b"image-bytes"
    assert (tmp_path / f"{ref}.png").exists()


def test_store_project_groups_under_project_folder_and_round_trips(tmp_path) -> None:
    project_id = uuid.uuid4()
    ref = store_project_screenshot(project_id, b"page-bytes", base_dir=tmp_path)
    # The ref is project-scoped (``<id>/<hex>``) but still opaque — no absolute path.
    assert ref.startswith(f"{project_id}/")
    hex_part = ref.split("/", 1)[1]
    assert len(hex_part) == 32 and all(c in "0123456789abcdef" for c in hex_part)
    # Bytes live under the per-project folder and round-trip through the same getter.
    assert (tmp_path / str(project_id) / f"{hex_part}.png").exists()
    assert get_screenshot(ref, base_dir=tmp_path) == b"page-bytes"


def test_get_rejects_project_ref_traversal(tmp_path) -> None:
    # A project segment that isn't a clean UUID never reaches the filesystem.
    assert get_screenshot(f"../../etc/{uuid.uuid4().hex}", base_dir=tmp_path) is None
    assert get_screenshot(f"{uuid.uuid4()}/../escape", base_dir=tmp_path) is None


def test_get_unknown_ref_is_none(tmp_path) -> None:
    assert get_screenshot(uuid.uuid4().hex, base_dir=tmp_path) is None


def test_get_rejects_malformed_or_traversal_refs(tmp_path) -> None:
    # A non-opaque ref never reaches the filesystem (no path traversal).
    assert get_screenshot("../../etc/passwd", base_dir=tmp_path) is None
    assert get_screenshot("a/b", base_dir=tmp_path) is None
    assert get_screenshot("", base_dir=tmp_path) is None


def test_placeholder_is_a_valid_png() -> None:
    png = placeholder_screenshot()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert png.endswith(b"IEND\xaeB`\x82")  # IEND chunk + its CRC
    assert len(png) > 50


# --- the S3 backend: a REAL boto3 round-trip (moto), not a fake ---------------

_S3_BUCKET = "polaris-shots-test"


@pytest.fixture
def s3_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """Point the indirection at an S3 backend backed by moto's in-process AWS mock,
    so the S3Store is exercised through a genuine boto3 client (create bucket, PUT,
    GET) with no network or real credentials."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_S3_BUCKET)
        monkeypatch.setattr(
            screenshot_storage,
            "get_settings",
            lambda: SimpleNamespace(
                screenshot_storage="s3",
                screenshot_s3_bucket=_S3_BUCKET,
                screenshot_s3_endpoint_url=None,
                screenshot_s3_region="us-east-1",
                screenshot_s3_prefix="screenshots",
                screenshot_dir="unused",
            ),
        )
        screenshot_storage.reset_backend_cache()  # fresh client inside this mock
        try:
            yield client
        finally:
            screenshot_storage.reset_backend_cache()


def test_s3_backend_round_trips_a_flat_ref(s3_backend) -> None:
    ref = store_screenshot(b"\x89PNG-s3-bytes")
    assert len(ref) == 32 and "/" not in ref  # still an opaque ref, no bucket/path
    assert get_screenshot(ref) == b"\x89PNG-s3-bytes"
    # The object lands under the configured prefix as <ref>.png.
    body = s3_backend.get_object(Bucket=_S3_BUCKET, Key=f"screenshots/{ref}.png")
    assert body["Body"].read() == b"\x89PNG-s3-bytes"


def test_s3_backend_groups_project_refs_under_the_prefix(s3_backend) -> None:
    project_id = uuid.uuid4()
    ref = store_project_screenshot(project_id, b"page-frame")
    assert ref.startswith(f"{project_id}/")  # project-scoped, still opaque
    assert get_screenshot(ref) == b"page-frame"
    hex_part = ref.split("/", 1)[1]
    key = f"screenshots/{project_id}/{hex_part}.png"
    assert s3_backend.get_object(Bucket=_S3_BUCKET, Key=key)["Body"].read() == b"page-frame"


def test_s3_get_unknown_ref_is_none(s3_backend) -> None:
    # A well-formed ref with no stored object → None (a clean miss, not a 500).
    assert get_screenshot(uuid.uuid4().hex) is None


def test_s3_get_rejects_malformed_ref_without_touching_s3(s3_backend) -> None:
    # A non-opaque ref is refused before any S3 call (no traversal into the bucket).
    assert get_screenshot("../../etc/passwd") is None
    assert get_screenshot("a/b") is None


# --- capture at the execution seam (RunLifecycle) ----------------------------

_ENV = TargetEnv(
    app_path="/unused",
    execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
    evidence_dir="/unused",
)


class _FakeRunner:
    framework = "fake"

    def __init__(self, results: list[ExecutionResult]) -> None:
        self._results = results

    def run(self, scripts: object, target_env: object) -> list[ExecutionResult]:
        return self._results

    def teardown(self, target_env: object) -> None:
        return None


def _exec_result(
    case_id: uuid.UUID, outcome: Outcome, *, screenshot: bytes | None = None
) -> ExecutionResult:
    return ExecutionResult(
        test_case_id=case_id,
        script_id=uuid.uuid4(),
        name=f"t-{case_id.hex[:6]}",
        outcome=outcome,
        evidence_ref="ev/x",
        screenshot=screenshot,
    )


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _run_lifecycle(
    session: AsyncSession, project_id: uuid.UUID, results: list[ExecutionResult]
):
    return await RunLifecycle(runner=_FakeRunner(results)).execute(
        session=session,
        project_id=project_id,
        scripts=[],
        target_env=_ENV,
        trigger=RunTrigger.MANUAL,
        mode=RunMode.B,
    )


async def test_failing_result_captures_stores_and_attaches_ref(
    db_session: AsyncSession, shot_dir
) -> None:
    project_id = await _project(db_session)
    case = await TestCaseRepository(db_session).add(make_test_case(project_id))
    run = await _run_lifecycle(
        db_session,
        project_id,
        [_exec_result(case.id, Outcome.FAIL, screenshot=b"shot")],
    )

    results = await ResultRepository(db_session).list_for_run(project_id, run.id)
    ref = results[0].screenshot_ref
    assert ref is not None
    assert get_screenshot(ref) == b"shot"  # stored + retrievable via the indirection


async def test_passing_result_attaches_no_screenshot(
    db_session: AsyncSession, shot_dir
) -> None:
    project_id = await _project(db_session)
    case = await TestCaseRepository(db_session).add(make_test_case(project_id))
    # Even with bytes present, a PASS captures nothing (only failures get a shot).
    run = await _run_lifecycle(
        db_session,
        project_id,
        [_exec_result(case.id, Outcome.PASS, screenshot=b"ignored")],
    )

    results = await ResultRepository(db_session).list_for_run(project_id, run.id)
    assert results[0].screenshot_ref is None


async def test_store_failure_does_not_break_the_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> str:
        raise OSError("disk full")

    monkeypatch.setattr("app.execution.lifecycle.store_screenshot", _boom)
    project_id = await _project(db_session)
    case = await TestCaseRepository(db_session).add(make_test_case(project_id))
    run = await _run_lifecycle(
        db_session, project_id, [_exec_result(case.id, Outcome.FAIL, screenshot=b"x")]
    )

    # The run still completes; the result simply carries no screenshot.
    results = await ResultRepository(db_session).list_for_run(project_id, run.id)
    assert run.status == STATUS_FAILED
    assert results[0].screenshot_ref is None


# --- the assembler propagates the ref to the finding -------------------------


class _NoResolver:
    async def journey(self, *args: object, **kwargs: object):
        raise AssertionError("resolver should not be called for an unlocated case")


async def test_assembler_copies_screenshot_ref_to_finding(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run = await RunRepository(db_session).add(make_run(project_id))
    case = await TestCaseRepository(db_session).add(
        make_test_case(project_id, target_node=None)
    )
    ref = "a" * 32
    result = await ResultRepository(db_session).add(
        make_result(
            project_id, run.id, case.id, outcome=Outcome.FAIL, screenshot_ref=ref
        )
    )

    findings = await FindingAssembler(db_session, resolver=_NoResolver()).assemble(
        project_id=project_id, results=[result]
    )
    assert len(findings) == 1
    assert findings[0].screenshot_ref == ref  # carried from the representative result


# --- has_screenshot + the authorized serve endpoint --------------------------


async def _personal_org_id(client: AsyncClient) -> uuid.UUID:
    body = (await client.get("/api/v1/orgs")).json()
    for org in body["items"]:
        if org["is_personal"]:
            return uuid.UUID(org["id"])
    raise AssertionError("authed user has no personal org")


async def _seed_finding(
    app: FastAPI, *, org_id: uuid.UUID, screenshot_ref: str | None
) -> uuid.UUID:
    """Commit a project (in ``org_id``) + run + result + finding; return finding id."""
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


async def _create_excluded_org(app: FastAPI) -> uuid.UUID:
    """An org the authed caller is NOT a member of."""
    async with app.state.sessionmaker() as session:
        org = await OrganizationRepository(session).add(
            Organization(name="Other Team", is_personal=False)
        )
        org_id = org.id
        await session.commit()
    return org_id


async def test_endpoint_streams_bytes_for_an_authorized_caller(
    authed_client: tuple[AsyncClient, FastAPI], shot_dir
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    ref = store_screenshot(b"\x89PNG-the-bytes")  # via the default (tmp) dir
    finding_id = await _seed_finding(app, org_id=org_id, screenshot_ref=ref)

    resp = await client.get(f"/api/v1/findings/{finding_id}/screenshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == b"\x89PNG-the-bytes"


async def test_endpoint_404_when_finding_has_no_screenshot(
    authed_client: tuple[AsyncClient, FastAPI], shot_dir
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    finding_id = await _seed_finding(app, org_id=org_id, screenshot_ref=None)
    assert (
        await client.get(f"/api/v1/findings/{finding_id}/screenshot")
    ).status_code == 404


async def test_endpoint_404_for_unknown_finding(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    resp = await client.get(f"/api/v1/findings/{uuid.uuid4()}/screenshot")
    assert resp.status_code == 404


async def test_endpoint_404_when_ref_recorded_but_bytes_missing(
    authed_client: tuple[AsyncClient, FastAPI], shot_dir
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    # A well-formed ref with no stored file (e.g. the ephemeral disk was wiped).
    finding_id = await _seed_finding(
        app, org_id=org_id, screenshot_ref=uuid.uuid4().hex
    )
    assert (
        await client.get(f"/api/v1/findings/{finding_id}/screenshot")
    ).status_code == 404


async def test_endpoint_404_for_a_finding_the_caller_cannot_view(
    authed_client: tuple[AsyncClient, FastAPI], shot_dir
) -> None:
    client, app = authed_client
    ref = store_screenshot(b"secret-screen")
    other_org = await _create_excluded_org(app)
    finding_id = await _seed_finding(app, org_id=other_org, screenshot_ref=ref)
    # Not a member of the finding's org → 404 (existence not leaked, ADR-0033).
    assert (
        await client.get(f"/api/v1/findings/{finding_id}/screenshot")
    ).status_code == 404


async def test_stub_run_attaches_a_placeholder_and_serves_it(
    authed_client: tuple[AsyncClient, FastAPI], shot_dir
) -> None:
    client, app = authed_client
    app.state.run_executor = StubRunExecutor()
    project = (
        await client.post(
            "/api/v1/projects",
            json={
                "name": "ShotDemo",
                "repo_url": "https://git.example/x.git",
                "app_url": "https://x.example",
                "auth_config_ref": "vault://x",
            },
        )
    ).json()

    run = await client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"mode": "mode_b", "strategy": "full_sweep"},
    )
    job_id = run.json()["run_id"]

    findings = (await client.get(f"/api/v1/runs/{job_id}/findings")).json()["findings"]
    assert len(findings) == 1
    assert findings[0]["has_screenshot"] is True  # payload reflects reality

    shot = await client.get(f"/api/v1/findings/{findings[0]['id']}/screenshot")
    assert shot.status_code == 200
    assert shot.headers["content-type"] == "image/png"
    assert shot.content.startswith(b"\x89PNG\r\n\x1a\n")  # the stub placeholder PNG
