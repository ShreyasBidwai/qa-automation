# QA Automation Platform — developer command wrapper.
#
# `docker compose up` is the canonical dev entrypoint (Engineering Standards §17);
# these targets wrap the common commands. CI mirrors them so "works on my
# machine" can't happen. Targets not yet wired print what they will do.
#
# Run from the repo root. `--project-directory .` makes the root `.env` the
# source of config and resolves build contexts relative to the repo root.

COMPOSE := docker compose --project-directory . -f infra/docker-compose.yml
COMPOSE_APP := docker compose --project-directory . -f infra/docker-compose.app.yml
COMPOSE_TEST := docker compose --project-directory . -f infra/docker-compose.yml -f infra/docker-compose.test.yml

.DEFAULT_GOAL := help
.PHONY: help up down dev-up dev-down build lint test test-runners test-e2e-runner test-embeddings audit migrate artifacts-dir

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

# Host-owned report dirs (777 so the non-root test containers can write into the
# bind mounts). Gitignored. A prerequisite of every target that mounts them.
artifacts-dir:
	@mkdir -p .artifacts/backend .artifacts/frontend .artifacts/e2e .artifacts/runner .artifacts/e2e-runner .artifacts/embed .artifacts/db-state
	@chmod 777 .artifacts/backend .artifacts/frontend .artifacts/e2e .artifacts/runner .artifacts/e2e-runner .artifacts/embed .artifacts/db-state

up: ## Run Polaris: packaged stack (Postgres + backend + single-origin web) — clone→running (docs/running.md)
	$(COMPOSE_APP) up -d --build --wait

down: ## Stop Polaris and remove containers (the db volume persists)
	$(COMPOSE_APP) down

dev-up: ## Dev stack (Vite hot-reload frontend on :5173) — for working on the UI, not packaging
	$(COMPOSE) up -d --build --wait

dev-down: ## Stop the dev stack
	$(COMPOSE) down

build: ## Build all Docker images
	$(COMPOSE_TEST) build

lint: artifacts-dir ## Lint + typecheck in Docker (ruff/black/mypy, eslint/prettier/tsc)
	$(COMPOSE_TEST) run --rm --no-deps --build backend-tests \
		sh -c "ruff check app && black --check app && mypy app"
	$(COMPOSE_TEST) run --rm --no-deps --build frontend-tests \
		sh -c "npm run lint && npm run format && npm run typecheck"

test: artifacts-dir ## Run all suites in Docker (pytest + vitest + playwright) + coverage gate
	$(COMPOSE_TEST) up -d --build --wait db backend frontend
	$(COMPOSE_TEST) run --rm --build backend-tests
	$(COMPOSE_TEST) run --rm --build frontend-tests
	$(COMPOSE_TEST) run --rm --build e2e

# Real-tooling tests run in the dedicated Laravel runner image (PHP + Composer +
# Pest), kept OUT of `make test` so the main suite stays fast. No Postgres: the
# target-under-test boots against in-memory sqlite (Architecture §9). Builds the
# image (composer install of the fixture app) and runs the `runner`-marked tests.
test-runners: artifacts-dir ## Build the Laravel runner image and run real PHP/Pest + PHP-helper tests
	$(COMPOSE_TEST) run --rm --no-deps --build runner-tests

# Real-browser lane (heavy: Playwright + browsers), kept OUT of `make test` so the
# main suite stays fast. Builds the Playwright runner image and runs, in a real
# browser, both the PlaywrightRunner (against a static fixture page) and the
# FrontendCrawler (crawls the fixture, writes pages/edges to the Brain). The
# fixture is served in-process by the test; the crawler test needs the db.
test-e2e-runner: artifacts-dir ## Build the Playwright runner image and run real-browser E2E (runner + crawler)
	$(COMPOSE_TEST) up -d --build --wait db
	$(COMPOSE_TEST) run --rm --build e2e-runner-tests

# Real-embedding lane (heavy: fastembed ONNX + model download), separate from
# `make test` so the main suite stays fast. Needs the db for the insert/search
# round-trip.
test-embeddings: artifacts-dir ## Build the embed image and run the real fastembed integration lane
	$(COMPOSE_TEST) up -d --build --wait db
	$(COMPOSE_TEST) run --rm --build embed-tests

# Real disposable-DB lane (heavy: B10, ADR-0043) — provisions throwaway Postgres
# databases from migrations and asserts table state at the DB end of the blast
# path. Kept OUT of `make test` so the main suite stays fast; needs the db.
test-db-state: artifacts-dir ## Build the backend test image and run the real disposable-DB lane
	$(COMPOSE_TEST) up -d --build --wait db
	$(COMPOSE_TEST) run --rm --build db-state-tests

# Scanning is scoped to shipped (production) dependencies: the backend audits
# requirements.txt (runtime only) and the frontend uses --omit=dev. Dev/test
# tooling advisories (e.g. vitest/esbuild) don't reach the deployed artifact and
# are triaged separately on their (breaking) upgrades.
# (The earlier starlette --ignore-vuln allowlist was removed once the FastAPI
# 0.137 / Starlette 1.3.1 bump landed — those advisories are now actually fixed.)
audit: artifacts-dir ## Scan shipped dependencies for known vulnerabilities (pip-audit, npm audit)
	$(COMPOSE_TEST) run --rm --no-deps --build backend-tests pip-audit -r requirements.txt
	$(COMPOSE_TEST) run --rm --no-deps --build frontend-tests npm audit --omit=dev --audit-level=high
	$(COMPOSE_TEST) run --rm --no-deps --build e2e npm audit --omit=dev --audit-level=high

migrate: ## Apply database migrations (forward-only) — one-shot; the packaged backend also auto-migrates on start
	$(COMPOSE_APP) run --rm backend alembic upgrade head
