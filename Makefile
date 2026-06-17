# QA Automation Platform — developer command wrapper.
#
# `docker compose up` is the canonical dev entrypoint (Engineering Standards §17);
# these targets wrap the common commands. CI mirrors them so "works on my
# machine" can't happen. Targets not yet wired print what they will do.
#
# Run from the repo root. `--project-directory .` makes the root `.env` the
# source of config and resolves build contexts relative to the repo root.

COMPOSE := docker compose --project-directory . -f infra/docker-compose.yml
COMPOSE_TEST := docker compose --project-directory . -f infra/docker-compose.yml -f infra/docker-compose.test.yml

.DEFAULT_GOAL := help
.PHONY: help up down test lint migrate

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

up: ## Start the dev stack (Postgres + backend + frontend), build and wait for healthy
	$(COMPOSE) up -d --build --wait

down: ## Stop the dev stack and remove containers (the db volume persists)
	$(COMPOSE) down

test: ## Run all suites inside Docker (backend pytest + frontend vitest + e2e playwright)
	$(COMPOSE_TEST) up -d --build --wait db backend frontend
	$(COMPOSE_TEST) run --rm --build backend-tests
	$(COMPOSE_TEST) run --rm --build frontend-tests
	$(COMPOSE_TEST) run --rm --build e2e

lint: ## Run linters and type checks (ruff, black --check, mypy, eslint, prettier)
	@echo "[make lint] not yet implemented — will wrap: ruff / black / mypy / eslint / prettier"

migrate: ## Apply database migrations (forward-only)
	$(COMPOSE) run --rm backend alembic upgrade head
