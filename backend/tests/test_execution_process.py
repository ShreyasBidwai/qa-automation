"""Execution subprocess env is SCRUBBED — generated test code can't read Polaris'
secrets (architecture-review DO-FIRST #1). Defense in depth beside the dual-DB guard.
"""

from __future__ import annotations

import pytest

from app.execution.process import (
    is_secret_env_key,
    run_process,
    scrubbed_environ,
)


@pytest.mark.parametrize(
    "key",
    [
        "CLAUDE_BRIDGE_TOKEN",
        "GIT_TOKEN",
        "TARGET_CREDENTIALS_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "POSTGRES_PASSWORD",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "DATABASE_URL",
        "CLAUDE_BRIDGE_URL",
        "SOME_FUTURE_SECRET",  # caught by substring, so a new secret is safe by default
    ],
)
def test_secret_keys_are_flagged(key: str) -> None:
    assert is_secret_env_key(key)


@pytest.mark.parametrize("key", ["PATH", "HOME", "LANG", "COMPOSER_HOME", "POSTGRES_DB"])
def test_operational_keys_survive(key: str) -> None:
    # The child still needs PATH/HOME/etc. to run pest; only secrets are stripped.
    assert not is_secret_env_key(key)


def test_scrubbed_environ_strips_secrets_keeps_operational(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_BRIDGE_TOKEN", "s3cr3t")
    monkeypatch.setenv("GIT_TOKEN", "ghp_xxx")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = scrubbed_environ()
    assert "CLAUDE_BRIDGE_TOKEN" not in env
    assert "GIT_TOKEN" not in env
    assert env.get("PATH") == "/usr/bin"


def test_run_process_child_env_has_no_secrets(monkeypatch) -> None:
    # The real seam: whatever env the spawned test process sees must exclude secrets,
    # keep operational vars, and honour the caller's explicit overlay.
    monkeypatch.setenv("CLAUDE_BRIDGE_TOKEN", "leak-me")
    monkeypatch.setenv("PATH", "/usr/bin")
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        captured["env"] = kwargs.get("env")

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()

    monkeypatch.setattr("app.execution.process.subprocess.run", fake_run)
    run_process(["pest"], "/app", {"DB_CONNECTION": "sqlite"}, 10.0)

    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert "CLAUDE_BRIDGE_TOKEN" not in child_env  # secret scrubbed
    assert child_env.get("PATH") == "/usr/bin"  # operational var preserved
    assert child_env.get("DB_CONNECTION") == "sqlite"  # overlay applied
