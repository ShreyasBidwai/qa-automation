# QA Automation Platform — developer command wrapper.
#
# `docker compose up` is the canonical dev entrypoint (Engineering Standards §17);
# these targets wrap the common commands. They are DECLARED BUT NOT YET IMPLEMENTED
# — each prints what it will do until the corresponding services and tooling land.
# CI mirrors these targets so "works on my machine" can't happen.

.DEFAULT_GOAL := help
.PHONY: help up down test lint migrate

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

up: ## Start the dev stack (Postgres + backend + frontend)
	@echo "[make up] not yet implemented — will wrap: docker compose up"

down: ## Stop the dev stack and remove containers
	@echo "[make down] not yet implemented — will wrap: docker compose down"

test: ## Run the full test suite inside Docker
	@echo "[make test] not yet implemented — will wrap: docker compose run --rm backend pytest / frontend vitest"

lint: ## Run linters and type checks (ruff, black --check, mypy, eslint, prettier)
	@echo "[make lint] not yet implemented — will wrap: ruff / black / mypy / eslint / prettier"

migrate: ## Apply database migrations (forward-only)
	@echo "[make migrate] not yet implemented — will wrap: docker compose run --rm backend alembic upgrade head"
