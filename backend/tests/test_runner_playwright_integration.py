"""Runner integration (real Playwright) — PlaywrightRunner against the fixture.

Marked ``e2e_runner``: runs ONLY in the ``runners/playwright`` image via
`make test-e2e-runner`, never in the fast backend suite. Serves the bundled
static fixture page in-process and drives a real browser through the
PlaywrightRunner: a passing spec → PASS and a deliberately-failing spec → FAIL,
with the JUnit/JSON reports + a trace captured as evidence and a clean teardown.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from app.execution.playwright_runner import PlaywrightRunner
from app.execution.types import DbHandle, DbRole, PestScript, TargetEnv
from app.models.enums import Outcome

pytestmark = pytest.mark.e2e_runner

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "playwright-app"

_PASSING_SPEC = """\
import { test, expect } from '@playwright/test';

test('fixture page renders and the button toggles status', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Fixture Ready' })).toBeVisible();
  await page.getByRole('button', { name: 'Toggle' }).click();
  await expect(page.getByTestId('status')).toHaveText('clicked');
});
"""

_FAILING_SPEC = """\
import { test, expect } from '@playwright/test';

test('a wrong expectation is detected as a failure', async ({ page }) => {
  await page.goto('/');
  // This heading does not exist — the assertion must fail (short timeout).
  await expect(
    page.getByRole('heading', { name: 'Nonexistent Heading' }),
  ).toBeVisible({ timeout: 3000 });
});
"""


class _QuietHandler(SimpleHTTPRequestHandler):
    # Matches the base signature; silences per-request stderr logging.
    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def fixture_url() -> Iterator[str]:
    handler = partial(_QuietHandler, directory=str(_FIXTURE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _script(name: str, code: str) -> PestScript:
    return PestScript(
        test_case_id=uuid.uuid4(), script_id=uuid.uuid4(), name=name, code=code
    )


def test_playwright_runner_executes_real_specs(
    fixture_url: str, tmp_path: Path
) -> None:
    evidence_dir = tmp_path / "evidence"
    target_env = TargetEnv(
        app_path=str(_FIXTURE_DIR),
        execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
        evidence_dir=str(evidence_dir),
        base_url=fixture_url,
    )
    scripts = [
        _script("fixture_pass", _PASSING_SPEC),
        _script("fixture_fail", _FAILING_SPEC),
    ]

    runner = PlaywrightRunner()  # node_project_dir="." → the image workdir
    try:
        results = runner.run(scripts, target_env)

        by_name = {r.name: r for r in results}
        assert by_name["fixture_pass"].outcome is Outcome.PASS
        assert by_name["fixture_fail"].outcome is Outcome.FAIL
        # Evidence captured: structured reports + at least one browser trace.
        assert (evidence_dir / "playwright-report.json").exists()
        assert (evidence_dir / "playwright-junit.xml").exists()
        assert all(r.evidence_ref == str(evidence_dir) for r in results)
        traces = list((evidence_dir / "artifacts").glob("**/trace.zip"))
        assert traces, "expected a captured Playwright trace"
    finally:
        runner.teardown(target_env)

    # No leaked generated project (Standards §11).
    assert not (Path(".").resolve() / ".pw-runs").exists()
