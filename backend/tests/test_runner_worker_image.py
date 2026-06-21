"""Promoted runner images ARE request-time worker images (B5, ADR-0036).

Run only in the heavy lanes (markers ``runner`` / ``e2e_runner``), inside the
toolchain images: assert the worker entrypoint + queue-worker wiring import and
build there, and that the stack's toolchain (Pest / Playwright + browsers) is
reachable — i.e. the same image that ran the test lane can now run the request-time
worker loop against real targets.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.composition import StubIngestor, StubRunExecutor
from app.api.jobs import make_handlers
from app.models.enums import JobKind
from app.services.job_worker import JobWorker


def _worker_wiring_is_runnable() -> None:
    """The worker entrypoint + handler wiring import and build in this image."""
    import app.worker  # the `python -m app.worker` entrypoint

    assert hasattr(app.worker, "main")
    handlers = make_handlers(ingestor=StubIngestor(), executor=StubRunExecutor())
    assert set(handlers) == {JobKind.RUN, JobKind.INGEST}
    # A worker is constructible (no DB connection is made by construction).
    engine = create_async_engine("postgresql+psycopg://u:p@localhost/none")
    worker = JobWorker(async_sessionmaker(engine), handlers, worker_id="image-check")
    assert worker is not None


@pytest.mark.runner
def test_pest_worker_image_has_toolchain_and_worker() -> None:
    """Laravel/Pest runner image: Pest toolchain reachable + worker runnable."""
    _worker_wiring_is_runnable()

    assert shutil.which("php") is not None, "PHP must be on the worker image PATH"
    assert shutil.which("composer") is not None, "Composer must be reachable"
    # Pest was installed into the bundled fixture at build time (composer install).
    pest = Path("tests/fixtures/laravel-app/vendor/bin/pest")
    assert pest.is_file(), f"Pest binary missing at {pest}"

    php = subprocess.run(
        ["php", "--version"], capture_output=True, text=True, timeout=60
    )
    assert php.returncode == 0 and "PHP" in php.stdout


@pytest.mark.e2e_runner
def test_playwright_worker_image_has_toolchain_browsers_and_worker() -> None:
    """Playwright runner image: Playwright + browsers reachable + worker runnable."""
    _worker_wiring_is_runnable()

    assert shutil.which("npx") is not None, "Node/npx must be on the worker image PATH"
    version = subprocess.run(
        ["npx", "playwright", "--version"], capture_output=True, text=True, timeout=120
    )
    assert version.returncode == 0 and "Version" in version.stdout

    # The official Playwright base image preinstalls browsers under /ms-playwright.
    browsers = Path("/ms-playwright")
    assert browsers.is_dir() and any(browsers.iterdir()), "browsers not preinstalled"
