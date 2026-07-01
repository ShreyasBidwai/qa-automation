# syntax=docker/dockerfile:1
# Multi-stage build (Engineering Standards §17): install dependencies into an
# isolated venv in a builder stage, then copy only the venv + app into a minimal
# runtime image that runs as a non-root user.

# ---- builder ---------------------------------------------------------------
FROM python:3.12.7-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
RUN python -m venv /opt/venv
COPY requirements.txt ./
RUN pip install -r requirements.txt

# ---- runtime ---------------------------------------------------------------
FROM python:3.12.7-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root system user (Standards §17).
RUN groupadd --system app \
    && useradd --system --gid app --no-create-home --home-dir /app app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app app ./app

USER app
EXPOSE 8000

# Owns the uvicorn server so SIGTERM flips readiness off before draining (§11).
CMD ["python", "-m", "app"]

# ---- test (dev/test deps + test sources; ephemeral, not for deployment) -----
FROM python:3.12.7-slim-bookworm AS test

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
# git: the GitCliProvider tests clone/checkout a real LOCAL fixture repo (no
# network). Not in the runtime image — ingestion jobs ship git in their worker.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
COPY requirements.txt requirements-dev.txt requirements-test.txt requirements-embed.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt

COPY alembic.ini pyproject.toml ./
COPY migrations ./migrations
COPY app ./app
COPY tests ./tests

CMD ["pytest"]

# ---- embed-test (real-embedding lane: test stage + fastembed) ---------------
# Heavy ONNX runtime kept OUT of the default test image; built/run only by
# `make test-embeddings`. fastembed downloads the model on first use.
FROM test AS embed-test

RUN pip install --no-cache-dir -r requirements-embed.txt

# ---- real (REAL-EXECUTION runner variant: toolchains co-located on PATH) -----
# NOT for the packaged stub stack. The decoupled `runner` worker (B5/ADR-0036)
# executes runs as SUBPROCESSES of its own process (app/execution/* →
# subprocess.run(["…/vendor/bin/pest"]) / node Playwright), so it needs the target
# toolchains on its PATH. Mirrors the install fragments from runners/laravel
# (PHP 8.2 + Composer) and runners/playwright (Node + Playwright + browsers), plus
# fastembed (local embeddings) and git (the ingester reads a checkout). The `claude`
# CLI is NOT installed here — it is bind-mounted from the host (compose override).
# Built/run only by `make up-real`; the slim `runtime` image stays untouched.
FROM runtime AS real

USER root

# PHP 8.2 (bookworm default) + the extensions real Laravel apps need, git (the
# ingester runs `git -C <repo> rev-parse HEAD`), the MySQL client (real apps target
# MySQL, not just sqlite), and the apt tooling for NodeSource. (Mirrors + extends
# runners/laravel/Dockerfile; unversioned `php-*` resolve to php8.2-* on bookworm.)
#   gd/imagick → image processing · redis → cache/queue · intl → localisation
#   mysql → pdo_mysql + mysqli · (bcmath/exif/sockets/zip/mbstring/xml/sqlite3 too)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        php-cli php-mbstring php-xml php-sqlite3 php-bcmath php-curl php-zip \
        php-gd php-redis php-intl php-mysql php-imagick \
        default-mysql-client \
        git unzip ca-certificates curl gnupg \
    && rm -rf /var/lib/apt/lists/*

# Git: the ingestor runs `git` against a bind-mounted repo owned by the HOST uid
# (≠ the container's `app` user), and `app`'s $HOME (/app) is root-owned/read-only.
# safe.directory=* in the SYSTEM config (/etc/gitconfig, read by every user) clears
# the "dubious ownership" refusal with no writable $HOME needed; GIT_CONFIG_GLOBAL
# points any global write at a writable path (avoids "~/.gitconfig: Permission denied").
RUN git config --system --add safe.directory '*'
ENV GIT_CONFIG_GLOBAL=/tmp/gitconfig

# Composer 2.8 (pinned), from the official image (mirrors runners/laravel).
COPY --from=composer:2.8 /usr/bin/composer /usr/bin/composer
ENV COMPOSER_NO_INTERACTION=1 COMPOSER_HOME=/tmp/composer

# Node 20 (NodeSource) for the Playwright runner.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# fastembed (local embeddings) — the slim runtime venv omits it; the runner needs
# it for EMBEDDING_PROVIDER=local (Brain node + document embeddings). Installed
# directly (the runtime venv already has the base deps; requirements-embed.txt also
# pulls the test deps, which the runner must not carry). Pin matches that lane.
RUN pip install --no-cache-dir fastembed==0.4.2

# Pre-download the embedding model at BUILD time into a shared, app-readable cache
# (the app user can't write $HOME/.cache — /app is root-owned). Bakes the model in,
# so the runner never downloads (or hits a read-only cache) at run time. Must match
# Settings.embedding_model (BAAI/bge-small-en-v1.5).
ENV FASTEMBED_CACHE_PATH=/opt/fastembed-cache \
    HF_HOME=/opt/hf-cache
RUN mkdir -p /opt/fastembed-cache /opt/hf-cache \
    && python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')" \
    && chmod -R a+rwX /opt/fastembed-cache /opt/hf-cache

# Playwright + the chromium browser (mirrors runners/playwright — install the
# browsers, not just the npm package). Pinned to 1.48.2 to match the runner lane.
# Browsers live in a shared path readable + executable by the non-root `app` user.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    NODE_PATH=/usr/lib/node_modules
RUN npm install -g @playwright/test@1.48.2 \
    && npx --yes playwright@1.48.2 install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

# Frontend-crawl driver dir (T4.2). ESM `import "@playwright/test"` ignores NODE_PATH
# and only walks `node_modules` up-tree, so the drivers need a `node_modules` next to
# them — symlinked to the global install (verified: chromium resolves). The .mjs
# drivers themselves are bind-mounted here from runners/playwright at run time
# (docker-compose.real.yml), single-sourced with the e2e-runner lane. Setting
# CRAWL_DRIVER_DIR turns the crawl phase ON for a run whose scope includes the UI
# layer (and whose project has an app_url) — so a run can drive the live app.
RUN mkdir -p /opt/crawl \
    && ln -s /usr/lib/node_modules /opt/crawl/node_modules \
    && chmod -R a+rX /opt/crawl
ENV CRAWL_DRIVER_DIR=/opt/crawl

# Composer cache + the app working dir must be writable by `app` at run time
# (composer install of the target + generated test files).
RUN mkdir -p /tmp/composer && chmod 0777 /tmp/composer

USER app

# The runner entrypoint (drains the durable jobs queue); overridden by compose, set
# here so the image is runnable standalone.
CMD ["python", "-m", "app.worker"]
