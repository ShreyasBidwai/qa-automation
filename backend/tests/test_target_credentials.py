"""Target-account credentials — the security-critical slice (ADR-0053).

Emphasis is on the secret-handling guarantees: encrypted at rest (the raw DB value is
never the plaintext), write-only (no payload ever returns it), never logged / in a run
summary, decrypted only via the designated accessor, RBAC-gated, and the mode drives
the run path. Hermetic — a per-test Fernet key is injected into the crypto module's
config hook (the real key comes from the environment, never the repo).
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.api.execution import OrchestratorRunExecutor
from app.api.ports import RunRequest
from app.credentials import (
    CredentialsDecryptError,
    CredentialsKeyError,
    ResolvedTargetLogin,
    decrypt_secret,
    encrypt_secret,
    resolve_target_login,
)
from app.models.enums import NodeKind, OrgRole, RunMode
from app.models.organization import Organization
from app.models.project import Project
from app.modes.selection import SelectionStrategyKind
from app.repositories.node_repository import NodeRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.target_credentials_repository import TargetCredentialsRepository
from tests.factories import make_node
from tests.test_api import _ENV, _FakeResolver, _StubGenerator, _StubRunner


@pytest.fixture(autouse=True)
def _crypto_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Inject a per-test Fernet key into the crypto module (never a repo key)."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        "app.credentials.crypto.get_settings",
        lambda: SimpleNamespace(target_credentials_key=key),
    )
    return key


def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.credentials.crypto.get_settings",
        lambda: SimpleNamespace(target_credentials_key=None),
    )


# --- crypto: encrypt at rest, decrypt only with the key ----------------------


def test_encrypt_produces_ciphertext_and_round_trips() -> None:
    token = encrypt_secret("hunter2pw")
    assert isinstance(token, bytes)
    assert token != b"hunter2pw" and b"hunter2pw" not in token  # not plaintext
    assert decrypt_secret(token) == "hunter2pw"


def test_encrypt_without_a_key_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_key(monkeypatch)
    with pytest.raises(CredentialsKeyError):
        encrypt_secret("anything")


def test_decrypt_rejects_a_bad_or_wrong_key_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(CredentialsDecryptError):
        decrypt_secret(b"not-a-valid-fernet-token")
    # A token from a different key cannot be decrypted (authenticated encryption).
    token = encrypt_secret("x")
    monkeypatch.setattr(
        "app.credentials.crypto.get_settings",
        lambda: SimpleNamespace(target_credentials_key=Fernet.generate_key().decode()),
    )
    with pytest.raises(CredentialsDecryptError):
        decrypt_secret(token)


# --- the decrypt-at-use accessor + its non-leaking result --------------------


def test_resolved_login_repr_never_exposes_the_secret() -> None:
    login = ResolvedTargetLogin(identifier="jane@example.com", secret="topsecret9")
    for rendered in (repr(login), str(login), f"{login}", "{}".format(login)):
        assert "topsecret9" not in rendered
    assert "jane@example.com" not in repr(login)  # identifier redacted
    assert login.secret == "topsecret9"  # the value is reachable at the point of use


async def _project(session: AsyncSession) -> uuid.UUID:
    project = await ProjectRepository(session).add(
        Project(name="P", slug=f"p-{uuid.uuid4().hex[:8]}", settings={})
    )
    return project.id


async def test_resolve_target_login_decrypts_only_via_the_accessor(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    await TargetCredentialsRepository(db_session).upsert(
        project_id,
        mode="specific_account",
        identifier="a@b.test",
        encrypted_secret=encrypt_secret("plaintextpw1"),
    )
    login = await resolve_target_login(db_session, project_id)
    assert login is not None
    assert login.identifier == "a@b.test"
    assert login.secret == "plaintextpw1"  # original plaintext, only here


async def test_resolve_returns_none_for_polaris_or_missing(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    assert await resolve_target_login(db_session, project_id) is None  # no record
    await TargetCredentialsRepository(db_session).upsert(
        project_id, mode="polaris_creates", identifier=None, encrypted_secret=None
    )
    assert await resolve_target_login(db_session, project_id) is None


# --- run-path selection: mode drives the path, no secret in the summary ------


async def _executor() -> OrchestratorRunExecutor:
    return OrchestratorRunExecutor(
        runner=_StubRunner(),
        target_env=_ENV,
        resolver_factory=lambda _session: _FakeResolver(),
        target_generator_factory=lambda session, _provider: _StubGenerator(session),
        ai_provider=StubAIProvider(),  # fixed provider (tests/stub path)
    )


async def _project_with_endpoint(session: AsyncSession) -> uuid.UUID:
    project_id = await _project(session)
    await NodeRepository(session).add(
        make_node(project_id, kind=NodeKind.ENDPOINT, name="GET /x")
    )
    return project_id


async def test_specific_account_drives_the_run_path(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = await _project_with_endpoint(db_session)
    await TargetCredentialsRepository(db_session).upsert(
        project_id,
        mode="specific_account",
        identifier="runner@acme.test",
        encrypted_secret=encrypt_secret("run-secret-1234"),
    )
    caplog.set_level(logging.DEBUG)
    execution = await (await _executor()).execute(
        session=db_session,
        project_id=project_id,
        request=RunRequest(
            mode=RunMode.B, strategy=SelectionStrategyKind.FULL_SWEEP, max_targets=50
        ),
    )
    assert execution.summary["auth_mode"] == "specific_account"
    # The secret appears in neither the summary nor anything logged during the run.
    assert "run-secret-1234" not in str(execution.summary)
    assert "run-secret-1234" not in caplog.text


async def test_polaris_creates_when_no_specific_account(
    db_session: AsyncSession,
) -> None:
    project_id = await _project_with_endpoint(db_session)
    execution = await (await _executor()).execute(
        session=db_session,
        project_id=project_id,
        request=RunRequest(
            mode=RunMode.B, strategy=SelectionStrategyKind.FULL_SWEEP, max_targets=50
        ),
    )
    assert execution.summary["auth_mode"] == "polaris_creates"


# --- API: encrypted at rest, write-only, RBAC -------------------------------


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_project(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/projects", json={"name": "Creds", "repo_url": "https://git/x.git"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_secret_is_encrypted_at_rest_and_never_in_the_write_response(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    project_id = await _create_project(client)
    secret = "sup3r-s3cret-value!"
    base = f"/api/v1/projects/{project_id}/credentials"

    resp = await client.put(
        base,
        json={"mode": "specific_account", "identifier": "a@b.test", "secret": secret},
    )
    assert resp.status_code == 200, resp.text
    assert secret not in resp.text  # the write response never echoes the secret

    # The raw DB value is ciphertext (not the plaintext), and only the accessor's
    # decrypt recovers it.
    async with app.state.sessionmaker() as session:
        record = await TargetCredentialsRepository(session).get(uuid.UUID(project_id))
    assert record is not None and record.encrypted_secret is not None
    assert secret.encode() not in record.encrypted_secret  # never stored in the clear
    assert decrypt_secret(record.encrypted_secret) == secret


async def test_get_returns_status_but_never_the_secret(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _create_project(client)
    base = f"/api/v1/projects/{project_id}/credentials"
    secret = "do-not-leak-7777"
    await client.put(
        base,
        json={"mode": "specific_account", "identifier": "x@y.test", "secret": secret},
    )

    got = await client.get(base)
    assert got.status_code == 200
    body = got.json()
    assert body == {
        "mode": "specific_account",
        "identifier": "x@y.test",
        "has_credentials": True,
    }
    assert "secret" not in body
    assert secret not in got.text  # plaintext absent from the whole response


async def test_has_credentials_reflects_reality_across_lifecycle(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _create_project(client)
    base = f"/api/v1/projects/{project_id}/credentials"

    # Unconfigured reads as polaris_creates / no creds.
    assert (await client.get(base)).json() == {
        "mode": "polaris_creates",
        "identifier": None,
        "has_credentials": False,
    }

    await client.put(
        base,
        json={
            "mode": "specific_account",
            "identifier": "a@b.test",
            "secret": "pw12345",
        },
    )
    assert (await client.get(base)).json()["has_credentials"] is True

    # Switching to polaris_creates clears the stored account + secret.
    await client.put(base, json={"mode": "polaris_creates"})
    cleared = (await client.get(base)).json()
    assert cleared["has_credentials"] is False and cleared["identifier"] is None

    # Re-set then DELETE clears it; a second delete is 404.
    await client.put(
        base,
        json={
            "mode": "specific_account",
            "identifier": "a@b.test",
            "secret": "pw12345",
        },
    )
    assert (await client.delete(base)).status_code == 204
    assert (await client.get(base)).json()["has_credentials"] is False
    assert (await client.delete(base)).status_code == 404


async def test_specific_account_requires_identifier_and_secret(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _create_project(client)
    base = f"/api/v1/projects/{project_id}/credentials"
    assert (
        await client.put(base, json={"mode": "specific_account", "secret": "pw12345"})
    ).status_code == 422  # missing identifier
    assert (
        await client.put(
            base, json={"mode": "specific_account", "identifier": "a@b.test"}
        )
    ).status_code == 422  # missing secret


async def test_write_refuses_and_stores_nothing_without_a_key(
    authed_client: tuple[AsyncClient, FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = authed_client
    project_id = await _create_project(client)
    _no_key(monkeypatch)  # encryption unavailable → must refuse, store nothing

    resp = await client.put(
        f"/api/v1/projects/{project_id}/credentials",
        json={
            "mode": "specific_account",
            "identifier": "a@b.test",
            "secret": "pw12345",
        },
    )
    assert resp.status_code == 503
    async with app.state.sessionmaker() as session:
        assert (
            await TargetCredentialsRepository(session).get(uuid.UUID(project_id))
            is None
        )


# --- RBAC: only MANAGE_PROJECT can set / view / clear ------------------------


async def _signup(client: AsyncClient) -> tuple[str, uuid.UUID]:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": f"c-{uuid.uuid4().hex[:10]}@e.test", "password": "passw0rd1"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


async def test_credentials_endpoints_require_manage_project(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    owner_token, owner_id = await _signup(client)
    viewer_token, viewer_id = await _signup(client)
    outsider_token, _ = await _signup(client)

    async with app.state.sessionmaker() as session:
        repo = OrganizationRepository(session)
        org = await repo.add(Organization(name="Team", is_personal=False))
        await repo.add_member(org.id, owner_id, OrgRole.OWNER)
        await repo.add_member(org.id, viewer_id, OrgRole.VIEWER)
        project = Project(
            name="Team", slug=f"team-{uuid.uuid4().hex[:8]}", org_id=org.id, settings={}
        )
        session.add(project)
        await session.flush()
        project_id = project.id
        await session.commit()

    base = f"/api/v1/projects/{project_id}/credentials"
    body = {"mode": "specific_account", "identifier": "a@b.test", "secret": "pw123456"}

    # Owner (MANAGE_PROJECT) can set; an in-org viewer is 403; an outsider is 404.
    assert (
        await client.put(base, json=body, headers=_h(owner_token))
    ).status_code == 200
    assert (
        await client.put(base, json=body, headers=_h(viewer_token))
    ).status_code == 403
    assert (
        await client.put(base, json=body, headers=_h(outsider_token))
    ).status_code == 404
    # GET + DELETE are gated the same way.
    assert (await client.get(base, headers=_h(viewer_token))).status_code == 403
    assert (await client.delete(base, headers=_h(viewer_token))).status_code == 403
    assert (await client.get(base, headers=_h(outsider_token))).status_code == 404
