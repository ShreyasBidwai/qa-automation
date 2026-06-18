# syntax=docker/dockerfile:1
# Playwright / browser E2E execution runner image (Architecture §9, TRD §8,
# Standards §17).
#
# Carries the target toolchain (Node + Playwright with browsers preinstalled and
# version-matched) AND Python 3.12, so the PlaywrightRunner (app/execution) and
# its pytest integration test run together against the bundled static fixture
# page. The fast backend suite runs in the separate backend image; this image is
# built/run only via `make test-e2e-runner`.
#
# Build context is the repo ROOT (it COPYs both backend/ and runners/playwright/);
# the Dockerfile lives in runners/playwright/.

# Pinned Playwright base — browsers are preinstalled and matched to
# @playwright/test 1.48.2, so the run is reproducible (Standards §17). Ships a
# non-root `pwuser`.
FROM mcr.microsoft.com/playwright:v1.48.2-jammy AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    # Browsers already live in the base image; never download during build.
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PATH="/opt/venv/bin:$PATH"

# Python 3.12 (the backend targets 3.12; jammy ships 3.10) via deadsnakes, in an
# isolated venv so it never collides with the system python the OS/Node tooling
# uses. DEBIAN_FRONTEND=noninteractive (export, build-scoped) keeps a transitive
# tzdata dependency from blocking the build on an interactive timezone prompt.
RUN export DEBIAN_FRONTEND=noninteractive \
    && apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        tzdata python3.12 python3.12-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/venv

WORKDIR /work

# Node deps first (best cache): @playwright/test pinned to the base browsers.
COPY runners/playwright/package.json runners/playwright/package-lock.json ./
RUN npm ci --no-audit --no-fund

# The stack-agnostic single-page crawl driver (T4.2), invoked per page by the
# Python PlaywrightPageFetcher. Lives next to node_modules so it resolves
# @playwright/test up-tree.
COPY runners/playwright/crawl_page.mjs ./

# Python deps — the backend test deps cover the execution adapter + pytest.
COPY backend/requirements.txt backend/requirements-dev.txt backend/requirements-test.txt ./
RUN pip install -r requirements-test.txt

# Backend code, tests, migrations, and the bundled static fixture page (under
# tests/fixtures/playwright-app/). The crawler integration test writes to the
# Brain, so migrations are needed for the conftest's `alembic upgrade head`.
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY backend/tests ./tests

# Non-root (Standards §17): the base ships `pwuser`; own /work so it can write
# generated projects + reports at runtime.
RUN chown -R pwuser:pwuser /work
USER pwuser

# Real-browser tests only (marker `e2e_runner`): the PlaywrightRunner drives the
# fixture page in a real browser and maps outcomes to Results with captured
# evidence. The fast suite lives in the backend image and excludes this marker.
CMD ["pytest", "-m", "e2e_runner", "tests/", \
     "--junitxml=.artifacts/junit.xml", "-p", "no:cacheprovider"]
