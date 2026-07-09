"""GitCliProvider + ingest_from_git (T2.5) — read-only checkout, no leaks, no secrets.

Fast lane: a LOCAL git fixture repo created in a temp dir (real ``git``, no
network, no live Gitea). Credential/read-only/failure paths use a spy runner.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.stub import StubEmbeddingProvider
from app.git.cli import GitCliProvider
from app.git.errors import GitCheckoutError
from app.git.url import authenticated_url, redact_url
from app.ingestion.commands import CommandResult
from app.ingestion.errors import CommandFailed
from app.ingestion.git_ingest import ingest_from_git
from app.ingestion.laravel.ingester import LaravelIngester
from app.models.model_node import EMBEDDING_DIM
from app.repositories.node_repository import NodeRepository
from tests.factories import make_project

_HTTPS_URL = "https://gitea.example.com/org/repo.git"
_TOKEN = "s3cr3t-ro-token"
_FIXTURE = str(Path(__file__).parent / "fixtures" / "laravel-app")


# --- local git fixture (real git, no network) -------------------------------
def _git(cwd: str, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture
def git_origin(tmp_path: Path) -> SimpleNamespace:
    origin = tmp_path / "origin"
    origin.mkdir()
    path = str(origin)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    # Allow fetching a reachable SHA over file:// transport (for the SHA test).
    _git(path, "config", "uploadpack.allowReachableSHA1InWant", "true")

    (origin / "first.txt").write_text("one")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "first")
    first = _git(path, "rev-parse", "HEAD")

    (origin / "second.txt").write_text("two")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "second")
    head = _git(path, "rev-parse", "HEAD")

    return SimpleNamespace(url=f"file://{path}", head=head, first=first)


# --- spy runner for credential / read-only / failure paths ------------------
def _spy_runner(calls: list[list[str]], *, fail_on: str | None = None):
    def runner(argv: Sequence[str], cwd: str | None, timeout: float) -> CommandResult:
        args = list(argv)
        calls.append(args)
        if fail_on is not None and fail_on in args:
            raise CommandFailed(f"git {fail_on} exited with code 128", returncode=128)
        if "rev-parse" in args:
            return CommandResult(0, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n", "")
        return CommandResult(0, "", "")

    return runner


# --- real-git checkout ------------------------------------------------------
def test_checkout_resolves_head_and_cleanup_removes_it(
    git_origin: SimpleNamespace,
) -> None:
    provider = GitCliProvider()
    handle = provider.checkout(git_origin.url, "main")
    try:
        assert handle.sha == git_origin.head
        assert handle.ref == "main"
        work = Path(handle.path)
        assert (work / "second.txt").read_text() == "two"
    finally:
        provider.cleanup(handle)
    assert not Path(handle.path).exists()


def test_checkout_of_specific_sha(git_origin: SimpleNamespace) -> None:
    provider = GitCliProvider()
    handle = provider.checkout(git_origin.url, git_origin.first)
    try:
        assert handle.sha == git_origin.first
        work = Path(handle.path)
        assert (work / "first.txt").exists()
        assert not (work / "second.txt").exists()  # checked out the older commit
    finally:
        provider.cleanup(handle)


# --- sync_into: persistent read-only checkout for execution (ADR-0074) ------
def test_sync_into_runs_readonly_persistent_verbs(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    provider = GitCliProvider(runner=_spy_runner(calls), token=_TOKEN)
    sha = provider.sync_into(_HTTPS_URL, "main", str(tmp_path))

    assert sha == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    joined = [" ".join(a) for a in calls]
    assert any(f"init -q {tmp_path}" in a for a in joined)
    assert any("remote add origin" in a for a in joined)
    assert any("fetch --no-tags --depth 1 origin main" in a for a in joined)
    assert any("checkout -q -f --detach FETCH_HEAD" in a for a in joined)
    # READ-ONLY + non-destructive to untracked deps: never push, never clean vendor/.
    assert not any("push" in a for a in joined)
    assert not any("clean" in a for a in joined)
    # The credentialed URL is used for auth (but is redacted from logs, tested below).
    assert any(f"oauth2:{_TOKEN}@" in a for a in joined)


def test_sync_into_redacts_credentials_on_failure(tmp_path: Path) -> None:
    provider = GitCliProvider(runner=_spy_runner([], fail_on="fetch"), token=_TOKEN)
    with pytest.raises(GitCheckoutError) as exc:
        provider.sync_into(_HTTPS_URL, "main", str(tmp_path))
    assert _TOKEN not in str(exc.value)


def test_sync_into_persists_and_preserves_untracked_on_resync(
    git_origin: SimpleNamespace, tmp_path: Path
) -> None:
    dest = tmp_path / "app"
    provider = GitCliProvider()  # real git against the local fixture
    sha = provider.sync_into(git_origin.url, "main", str(dest))
    assert sha == git_origin.head
    assert (dest / "second.txt").read_text() == "two"

    # An untracked file (mimicking an installed vendor/) MUST survive a re-sync, so a
    # run never triggers a needless composer reinstall.
    (dest / "vendor_marker").write_text("keep")
    sha2 = provider.sync_into(git_origin.url, "main", str(dest))
    assert sha2 == git_origin.head
    assert (dest / "vendor_marker").read_text() == "keep"


# --- cleanup on failure (no leaked temp dirs) -------------------------------
def test_checkout_cleans_up_temp_dir_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(*args: object, **kwargs: object) -> str:
        path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
        created.append(path)
        return path

    monkeypatch.setattr("app.git.cli.tempfile.mkdtemp", tracking_mkdtemp)
    provider = GitCliProvider(runner=_spy_runner([], fail_on="fetch"), token=_TOKEN)

    with pytest.raises(GitCheckoutError) as exc:
        provider.checkout(_HTTPS_URL, "main")

    assert created and not os.path.exists(created[0])  # temp dir removed
    assert _TOKEN not in str(exc.value)  # error is credential-redacted


# --- credential handling: injected, never logged ---------------------------
def test_authenticated_url_injects_token_and_redact_strips_it() -> None:
    url = authenticated_url(_HTTPS_URL, _TOKEN, "oauth2")
    assert url == f"https://oauth2:{_TOKEN}@gitea.example.com/org/repo.git"
    redacted = redact_url(url)
    assert _TOKEN not in redacted and "oauth2" not in redacted
    assert redacted == _HTTPS_URL
    # Non-http URLs (file/ssh/local) never get a token.
    assert authenticated_url("file:///tmp/repo", _TOKEN) == "file:///tmp/repo"


def test_checkout_injects_token_but_never_logs_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[list[str]] = []
    provider = GitCliProvider(runner=_spy_runner(calls), token=_TOKEN)
    with caplog.at_level(logging.INFO):
        handle = provider.checkout(_HTTPS_URL, "main")
    provider.cleanup(handle)

    # The credentialed URL IS used in the git command (so auth works) ...
    assert any(f"oauth2:{_TOKEN}@gitea.example.com" in " ".join(args) for args in calls)
    # ... but neither the token nor the credentialed URL ever reaches the logs.
    assert _TOKEN not in caplog.text
    assert "oauth2:" not in caplog.text
    # What IS logged is the redacted (credential-free) repo URL.
    checkout_records = [r for r in caplog.records if r.message == "git.checkout"]
    assert checkout_records
    repos = [str(getattr(r, "repo", "")) for r in checkout_records]
    assert _HTTPS_URL in repos  # host logged, token stripped
    assert all(_TOKEN not in repo for repo in repos)


# --- read-only: no push/write path ------------------------------------------
def test_provider_is_read_only() -> None:
    assert hasattr(GitCliProvider, "checkout")
    assert hasattr(GitCliProvider, "cleanup")
    for forbidden in ("push", "commit", "write", "publish"):
        assert not hasattr(GitCliProvider, forbidden)


def test_checkout_runs_only_read_only_git_subcommands() -> None:
    calls: list[list[str]] = []
    provider = GitCliProvider(runner=_spy_runner(calls))
    handle = provider.checkout("file:///tmp/repo", "main")
    provider.cleanup(handle)
    flat = [token for args in calls for token in args]
    for forbidden in ("push", "commit", "send-pack", "update-ref"):
        assert forbidden not in flat


# --- end-to-end: ingest_from_git tags the Brain with the real SHA -----------
def _no_ingest_subprocess(
    argv: Sequence[str], cwd: str | None, timeout: float
) -> CommandResult:
    """Fail if ingestion shells out — proves the Brain is built from source only."""
    raise AssertionError(f"ingestion shelled out — must read source only: {list(argv)}")


@pytest.fixture
def laravel_git_origin(tmp_path: Path) -> SimpleNamespace:
    """A real git repo whose tree IS the Laravel fixture, so a checkout yields source
    the STATIC ingester can read (no app boot)."""
    origin = tmp_path / "laravel-origin"
    shutil.copytree(_FIXTURE, origin)
    path = str(origin)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "laravel app")
    head = _git(path, "rev-parse", "HEAD")
    return SimpleNamespace(url=f"file://{path}", head=head)


async def test_ingest_from_git_populates_brain_with_real_sha(
    db_session: AsyncSession,
    laravel_git_origin: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(*args: object, **kwargs: object) -> str:
        path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
        created.append(path)
        return path

    monkeypatch.setattr("app.git.cli.tempfile.mkdtemp", tracking_mkdtemp)

    project = make_project()
    db_session.add(project)
    await db_session.flush()

    result = await ingest_from_git(
        session=db_session,
        project_id=project.id,
        repo_url=laravel_git_origin.url,
        ref="main",
        provider=GitCliProvider(),  # real git against the local fixture
        ingester=LaravelIngester(
            runner=_no_ingest_subprocess,  # static-only; raises if it shells out
            embedding_provider=StubEmbeddingProvider(EMBEDDING_DIM),
        ),
    )

    # Brain nodes are tagged with the REAL checked-out commit SHA.
    assert result.source_sha == laravel_git_origin.head
    nodes = await NodeRepository(db_session).list(project.id)
    assert nodes
    assert all(n.source_sha == laravel_git_origin.head for n in nodes)

    # The temp clone was cleaned up by ingest_from_git (no leak).
    assert created and not os.path.exists(created[0])
