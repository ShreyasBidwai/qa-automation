# syntax=docker/dockerfile:1
# Laravel / Pest execution runner image (Architecture §9, TRD §8, Standards §17).
#
# Carries the target toolchain (PHP 8.2 + Composer + Pest + nikic/php-parser)
# AND Python, so the PestRunner (app/execution) and its pytest integration tests
# run together against the bootable Laravel fixture. The fast backend suite runs
# in the separate backend image; this image is built/run only via
# `make test-runners`.
#
# Build context is ./backend (so it can COPY the backend code + the fixture under
# tests/fixtures/laravel-app); the Dockerfile lives in runners/laravel/.

FROM python:3.12.7-slim-bookworm AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COMPOSER_NO_INTERACTION=1 \
    COMPOSER_HOME=/home/runner/.composer

# PHP 8.2 (Debian bookworm default) + the extensions Laravel, Pest, and Composer
# need. Pinned via the base image + Composer tag below; the PHP packages are
# pinned by the fixture app's committed composer.lock.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        php-cli php-mbstring php-xml php-sqlite3 php-bcmath php-curl php-zip \
        git unzip \
    && rm -rf /var/lib/apt/lists/*

# Composer 2.8 (pinned) from the official image.
COPY --from=composer:2.8 /usr/bin/composer /usr/bin/composer

# Non-root user (Standards §17); owns /work so it installs vendor + writes
# generated test files at runtime.
RUN groupadd --system runner \
    && useradd --system --gid runner --create-home --home-dir /home/runner runner

WORKDIR /work

# Python deps — the backend test deps cover the execution + ingestion code and
# pytest. Installed as root into the system environment.
COPY requirements.txt requirements-dev.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt

# Backend code, tests, and the bootable Laravel fixture (fixtures live under
# tests/). alembic.ini is referenced lazily by conftest and unused here (no
# Postgres), but copied so imports never surprise us.
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY tests ./tests

RUN chown -R runner:runner /work
USER runner

# composer install the fixture at build time → self-contained, reproducible
# image; vendor is owned by `runner` so it stays writable at runtime.
WORKDIR /work/tests/fixtures/laravel-app
RUN composer install --no-interaction --prefer-dist --no-progress --no-ansi

WORKDIR /work

# Real-tooling tests only (marker `runner`); the fast suite lives in the backend
# image. No Postgres is touched here — the target runs against in-memory sqlite.
CMD ["pytest", "-m", "runner", \
     "tests/test_runner_pest_integration.py", "tests/test_helper_php_shape.py", \
     "--junitxml=.artifacts/junit.xml", "-p", "no:cacheprovider"]
