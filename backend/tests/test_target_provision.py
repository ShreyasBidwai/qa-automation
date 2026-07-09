"""Auto-provision of the PHP target checkout (ADR-0074).

The provisioner syncs the repo + ``composer install``s ONLY when needed, is a no-op
for local checkouts and browser runs, and is BEST-EFFORT: any failure returns False
so a run degrades to the graceful "skip API layer" path rather than breaking.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from app.execution.process import ProcessResult
from app.execution.provision import TargetAppProvisioner

_URL = "https://git.example.com/org/app.git"


class _FakeGit:
    """Records sync_into calls; optionally raises to exercise the best-effort path."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._fail = fail

    def sync_into(self, repo_url: str, ref: str, dest: str) -> str:
        self.calls.append((repo_url, ref, dest))
        if self._fail:
            raise RuntimeError("git sync failed")
        return "deadbeef"


class _FakeProc:
    """A Process spy: records composer invocations; returns a chosen exit code."""

    def __init__(self, returncode: int = 0, *, on_call=None) -> None:
        self.calls: list[tuple[list[str], str | None, dict[str, str], float]] = []
        self._rc = returncode
        self._on_call = on_call

    def __call__(
        self,
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout: float,
    ) -> ProcessResult:
        self.calls.append((list(argv), cwd, dict(env or {}), timeout))
        if self._on_call is not None:
            self._on_call(cwd)
        return ProcessResult(self._rc, "", "" if self._rc == 0 else "boom")


def _prov(git: _FakeGit, proc: _FakeProc) -> TargetAppProvisioner:
    return TargetAppProvisioner(git_sync=git, process=proc)


def test_pest_git_url_syncs_then_composer_installs(tmp_path: Path) -> None:
    app = str(tmp_path)
    git, proc = _FakeGit(), _FakeProc()
    ok = _prov(git, proc).ensure_php_checkout(
        repo_path=_URL, app_path=app, framework="pest"
    )
    assert ok is True
    assert git.calls == [(_URL, "HEAD", app)]  # synced the remote into app_path
    assert proc.calls[0][0][:2] == ["composer", "install"]
    assert proc.calls[0][1] == app  # run in the checkout dir
    assert (tmp_path / ".polaris-composer.sha").read_text() == "no-lock"


def test_local_checkout_is_a_noop(tmp_path: Path) -> None:
    # resolve_target_config sets app_path == repo for a local path → nothing to sync.
    app = str(tmp_path)
    git, proc = _FakeGit(), _FakeProc()
    ok = _prov(git, proc).ensure_php_checkout(
        repo_path=app, app_path=app, framework="pest"
    )
    assert ok is True
    assert git.calls == [] and proc.calls == []


def test_browser_framework_is_a_noop(tmp_path: Path) -> None:
    git, proc = _FakeGit(), _FakeProc()
    ok = _prov(git, proc).ensure_php_checkout(
        repo_path=_URL, app_path=str(tmp_path), framework="playwright"
    )
    assert ok is True
    assert git.calls == [] and proc.calls == []


def test_composer_skipped_when_vendor_and_lock_unchanged(tmp_path: Path) -> None:
    app = str(tmp_path)
    (tmp_path / "composer.lock").write_bytes(b"lock-v1")

    def _make_vendor(cwd: str | None) -> None:
        (Path(cwd) / "vendor").mkdir(exist_ok=True)  # type: ignore[arg-type]
        (Path(cwd) / "vendor" / "autoload.php").write_text("x")  # type: ignore[arg-type]

    # First run installs (no vendor yet) and records the lock hash in the marker.
    proc1 = _FakeProc(on_call=_make_vendor)
    TargetAppProvisioner(git_sync=_FakeGit(), process=proc1).ensure_php_checkout(
        repo_path=_URL, app_path=app, framework="pest"
    )
    assert len(proc1.calls) == 1

    # Second run: vendor/ + marker present and the lock is unchanged → skip composer.
    proc2 = _FakeProc()
    TargetAppProvisioner(git_sync=_FakeGit(), process=proc2).ensure_php_checkout(
        repo_path=_URL, app_path=app, framework="pest"
    )
    assert proc2.calls == []

    # Third run: composer.lock changed → composer must run again.
    (tmp_path / "composer.lock").write_bytes(b"lock-v2")
    proc3 = _FakeProc(on_call=_make_vendor)
    TargetAppProvisioner(git_sync=_FakeGit(), process=proc3).ensure_php_checkout(
        repo_path=_URL, app_path=app, framework="pest"
    )
    assert len(proc3.calls) == 1


def test_sync_failure_is_best_effort(tmp_path: Path) -> None:
    git, proc = _FakeGit(fail=True), _FakeProc()
    ok = _prov(git, proc).ensure_php_checkout(
        repo_path=_URL, app_path=str(tmp_path), framework="pest"
    )
    assert ok is False  # no raise — the run falls back to the skip-API path
    assert proc.calls == []  # never reached composer


def test_composer_failure_is_best_effort(tmp_path: Path) -> None:
    git, proc = _FakeGit(), _FakeProc(returncode=2)
    ok = _prov(git, proc).ensure_php_checkout(
        repo_path=_URL, app_path=str(tmp_path), framework="pest"
    )
    assert ok is False
    assert not (tmp_path / ".polaris-composer.sha").exists()  # marker not written
