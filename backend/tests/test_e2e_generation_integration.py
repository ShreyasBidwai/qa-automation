"""E2E generation → execution (real browser) — the generate→execute edge.

Marked ``e2e_runner``: runs ONLY in the runners/playwright image via
`make test-e2e-runner`. Generates E2E cases through the full pipeline
(journey → deterministic plan → rendered spec → CaseMergeService) and then
EXECUTES the rendered specs with the T4.1 PlaywrightRunner against the served
fixture: a real spec passes; a deliberately-wrong assertion is caught as a
failure. This is the fixture validation for UI generation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import FailureEvidence, Subgraph, TriageLabel
from app.execution.playwright_runner import PlaywrightRunner
from app.execution.types import DbHandle, DbRole, PestScript, TargetEnv
from app.generation.e2e_generator import E2EGenerator
from app.models.enums import NodeKind, Outcome
from app.models.model_node import ModelNode
from app.repositories.node_repository import NodeRepository
from tests.factories import make_node, make_project

pytestmark = pytest.mark.e2e_runner

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "playwright-app"

_PASS_SPEC = """import { test, expect } from '@playwright/test';

test('fixture renders the heading', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Fixture Ready' })).toBeVisible();
});
"""

_FAIL_SPEC = """import { test, expect } from '@playwright/test';

test('a wrong assertion is caught as failure', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Nonexistent Heading' }),
  ).toBeVisible({ timeout: 3000 });
});
"""


class _SpecProvider:
    """A provider that returns a fixed, realistic, executable spec (the render edge)."""

    def __init__(self, code: str) -> None:
        self._code = code

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str:
        return self._code

    def triage(self, failure: FailureEvidence) -> TriageLabel:  # pragma: no cover
        raise NotImplementedError


class _QuietHandler(SimpleHTTPRequestHandler):
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


async def _seed_page(
    session: AsyncSession, project_id: uuid.UUID, path: str
) -> ModelNode:
    return await NodeRepository(session).add(
        make_node(
            project_id,
            kind=NodeKind.PAGE,
            name=path,
            attributes={"path": path, "title": "Fixture", "forms": []},
        )
    )


async def test_generated_specs_execute_via_playwright_runner(
    fixture_url: str, db_session: AsyncSession, tmp_path: Path
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    project_id = project.id

    page_pass = await _seed_page(db_session, project_id, "/pass")
    page_fail = await _seed_page(db_session, project_id, "/fail")

    pass_gen = E2EGenerator(
        provider=_SpecProvider(_PASS_SPEC), budget_tokens=2048, generated_by="stub"
    )
    fail_gen = E2EGenerator(
        provider=_SpecProvider(_FAIL_SPEC), budget_tokens=2048, generated_by="stub"
    )
    pass_results = await pass_gen.generate_and_persist(
        session=db_session, project_id=project_id, page_node_id=page_pass.id
    )
    fail_results = await fail_gen.generate_and_persist(
        session=db_session, project_id=project_id, page_node_id=page_fail.id
    )

    # Execute the GENERATED specs with the T4.1 runner against the fixture.
    runner = PlaywrightRunner()
    target = TargetEnv(
        app_path=str(_FIXTURE_DIR),
        execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
        evidence_dir=str(tmp_path / "evidence"),
        base_url=fixture_url,
    )
    scripts = [
        PestScript(
            uuid.uuid4(), uuid.uuid4(), "e2e_pass", pass_results[0].test_script.code
        ),
        PestScript(
            uuid.uuid4(), uuid.uuid4(), "e2e_fail", fail_results[0].test_script.code
        ),
    ]
    try:
        results = runner.run(scripts, target)
    finally:
        runner.teardown(target)

    by_name = {r.name: r for r in results}
    assert by_name["e2e_pass"].outcome is Outcome.PASS
    assert by_name["e2e_fail"].outcome is Outcome.FAIL
