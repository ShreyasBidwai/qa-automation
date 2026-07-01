"""Claude bridge — the host daemon (bridge_server) + the client runner (claude_bridge).

The bridge keeps the host's Claude login on the HOST: the container POSTs {prompt,
model} to a token-guarded daemon that runs `claude -p` as the logged-in user, instead
of mounting ~/.claude (which corrupts the host login on up/down). These tests cover
the security-critical seams with NO real claude and NO network — the daemon's pure
``handle_generate`` (auth, model allow-list, argv construction) and the client
runner's HTTP mapping onto the provider's error taxonomy.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from app.ai.claude_bridge import make_bridge_runner
from app.ai.errors import AIInvocationError, AITransientError
from app.bridge.server import (
    ConcurrencyGate,
    handle_generate,
    is_authorized,
    model_allowed,
    run_claude,
)

_ARGV = ["claude", "-p", "--output-format", "json", "--model", "sonnet"]


# --- client: make_bridge_runner ---------------------------------------------


class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_bridge_runner_posts_prompt_and_model_and_returns_result(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse({"returncode": 0, "stdout": "ENVELOPE", "stderr": ""})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    runner = make_bridge_runner("http://host.docker.internal:8787/", "tok")

    result = runner(_ARGV, "the prompt", 120.0)

    assert (result.returncode, result.stdout) == (0, "ENVELOPE")
    assert captured["url"] == "http://host.docker.internal:8787/generate"
    # Only the prompt + model cross to the host — never the raw argv (no host RCE).
    assert captured["body"] == {
        "prompt": "the prompt",
        "model": "sonnet",
        "timeout": 120.0,
    }
    assert captured["auth"] == "Bearer tok"


def test_bridge_runner_maps_bad_token_to_fatal(monkeypatch) -> None:
    def boom(request, timeout=None):  # noqa: ANN001
        raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(AIInvocationError, match="token"):
        make_bridge_runner("http://x", "tok")(_ARGV, "p", 10.0)


def test_bridge_runner_maps_unreachable_to_transient(monkeypatch) -> None:
    def boom(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(AITransientError, match="unreachable"):
        make_bridge_runner("http://x", "tok")(_ARGV, "p", 10.0)


# --- daemon: handle_generate (pure auth/validation/dispatch) -----------------


def _ok_runner(prompt: str, model: str, timeout: float) -> dict:
    return {"returncode": 0, "stdout": f"ran {model}", "stderr": ""}


_ALLOWED = frozenset({"sonnet"})


def test_handle_generate_rejects_a_bad_token() -> None:
    status, _ = handle_generate(
        {"prompt": "p", "model": "sonnet"},
        "Bearer wrong",
        token="right",
        allowed=_ALLOWED,
        claude_runner=_ok_runner,
    )
    assert status == 401


def test_handle_generate_rejects_a_malformed_body() -> None:
    status, _ = handle_generate(
        {"model": "sonnet"},  # no prompt
        "Bearer t",
        token="t",
        allowed=_ALLOWED,
        claude_runner=_ok_runner,
    )
    assert status == 400


def test_handle_generate_rejects_a_disallowed_model() -> None:
    status, body = handle_generate(
        {"prompt": "p", "model": "gpt-4"},
        "Bearer t",
        token="t",
        allowed=_ALLOWED,
        claude_runner=_ok_runner,
    )
    assert status == 400 and "not allowed" in body["error"]


def test_handle_generate_runs_an_allowed_model() -> None:
    seen: dict = {}

    def runner(prompt: str, model: str, timeout: float) -> dict:
        seen.update(prompt=prompt, model=model, timeout=timeout)
        return {"returncode": 0, "stdout": "x", "stderr": ""}

    status, body = handle_generate(
        {"prompt": "hello", "model": "sonnet", "timeout": 42},
        "Bearer t",
        token="t",
        allowed=_ALLOWED,
        claude_runner=runner,
    )
    assert status == 200 and body["stdout"] == "x"
    assert seen == {"prompt": "hello", "model": "sonnet", "timeout": 42.0}


def test_model_allowed_accepts_aliases_and_official_ids_only() -> None:
    assert model_allowed("sonnet", _ALLOWED)  # in the allow-list
    assert model_allowed("claude-opus-4-8", _ALLOWED)  # official id pattern
    assert not model_allowed("opus", _ALLOWED)  # neither listed nor a claude- id
    assert not model_allowed("rm -rf /", _ALLOWED)  # junk rejected


def test_is_authorized_requires_a_set_token_and_the_bearer_prefix() -> None:
    assert is_authorized("Bearer abc", "abc")
    assert not is_authorized("Bearer abc", "")  # unset token denies everything
    assert not is_authorized("abc", "abc")  # missing "Bearer " prefix


# --- daemon: run_claude (argv construction + stdin) --------------------------


def test_run_claude_builds_the_argv_and_passes_the_prompt_on_stdin(monkeypatch) -> None:
    captured: dict = {}

    class _Done:
        returncode = 0
        stdout = "OUT"
        stderr = ""

    def fake_run(argv, **kwargs):  # noqa: ANN001
        captured["argv"] = argv
        captured["input"] = kwargs.get("input")
        captured["timeout"] = kwargs.get("timeout")
        return _Done()

    monkeypatch.setattr("app.bridge.server.subprocess.run", fake_run)

    out = run_claude("the prompt", "sonnet", 99.0, cli="claude", max_timeout=300.0)

    assert out == {"returncode": 0, "stdout": "OUT", "stderr": ""}
    # The argv is built HERE from the validated model — a list, no shell.
    assert captured["argv"] == [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--model",
        "sonnet",
    ]
    assert captured["input"] == "the prompt"
    assert captured["timeout"] == 99.0  # min(timeout, max_timeout)


def test_run_claude_reports_a_missing_cli_clearly(monkeypatch) -> None:
    def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise FileNotFoundError()

    monkeypatch.setattr("app.bridge.server.subprocess.run", boom)
    out = run_claude("p", "sonnet", 10.0, cli="claude")
    assert out["returncode"] == 127 and "not found" in out["stderr"]


# --- ConcurrencyGate: N-way claude, but the OAuth refresh stays serial ---------


def _probe_max_concurrency(gate: ConcurrencyGate, n_calls: int) -> dict[str, int]:
    """Run ``n_calls`` fns through the gate from threads, recording how many ran at
    once and the concurrency the FIRST-entering call saw (the warm-up must be alone)."""
    lock = threading.Lock()
    state = {"current": 0, "max": 0, "first_seen": 0}

    def fn() -> dict[str, int]:
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
            if state["first_seen"] == 0:
                state["first_seen"] = state["current"]
        time.sleep(0.05)
        with lock:
            state["current"] -= 1
        return {"returncode": 0}

    threads = [threading.Thread(target=lambda: gate.run(fn)) for _ in range(n_calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return state


def test_gate_is_fully_serial_at_concurrency_one() -> None:
    # The safe default: byte-for-byte the old behaviour — one claude at a time.
    state = _probe_max_concurrency(ConcurrencyGate(1, warm_interval=0.0), n_calls=5)
    assert state["max"] == 1


def test_gate_runs_calls_concurrently_but_warms_up_exclusively() -> None:
    # concurrency=4: the FIRST call (a stale window) runs ALONE and refreshes the
    # token; then the rest run concurrently, capped at N. Proves both invariants.
    state = _probe_max_concurrency(ConcurrencyGate(4, warm_interval=600.0), n_calls=6)
    assert state["first_seen"] == 1  # the warm-up ran with no peer (refresh-safe)
    assert 2 <= state["max"] <= 4  # then real concurrency, never above N


def test_gate_re_warms_after_the_interval_elapses() -> None:
    # A second stale window re-warms exclusively (single-flight), never racing.
    gate = ConcurrencyGate(3, warm_interval=0.0)  # every window is "stale" → warms
    # Serial-ish because each call re-warms; the point is it never errors/deadlocks
    # and still admits work. Two sequential calls both complete.
    assert gate.run(lambda: {"ok": 1}) == {"ok": 1}
    assert gate.run(lambda: {"ok": 2}) == {"ok": 2}
