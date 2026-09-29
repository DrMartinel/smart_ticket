# core-api developer commands. Run from services/core-api; `make` lists them.
#
# CI (.github/workflows/) spells its commands out rather than calling these
# targets, so a change here that CI should see must be made there too.

.DEFAULT_GOAL := help
SHELL := /bin/bash

ROOT   := ../..
MANAGE := uv run python manage.py

# The Dockerized Postgres and Redis, on their host ports (5434 / 6380, not the
# defaults, to avoid collisions). Override on the command line:
# `make runserver DATABASE_URL=...`.
#
# DJANGO_SETTINGS_MODULE is deliberately NOT exported: manage.py and
# config/celery.py default to `development`, and pytest.ini selects `test`.
# Exporting it would override pytest.ini and run the tests on dev settings.
DATABASE_URL      ?= postgresql://app_user:app_password@localhost:5434/smart_triage
CELERY_BROKER_URL ?= redis://localhost:6380/0
export DATABASE_URL CELERY_BROKER_URL

# ruff is pinned to match lint.yml; bump both together.
RUFF := uvx ruff@0.16.7

# Extra arguments: `make test ARGS="-k router -x"`, `make migrate ARGS="tickets 0001"`.
ARGS ?=

##@ Setup

.PHONY: install
install: ## Install the workspace (every member: the root project has no deps of its own)
	cd $(ROOT) && uv sync --all-packages

##@ Tests and checks

.PHONY: test
test: ## Unit tests (needs the Dockerized Postgres)
	uv run pytest -q $(ARGS)

.PHONY: coverage
coverage: ## 100% coverage gate on masking + router (the release gate)
	uv run pytest -q --cov=apps.tickets.utils.masking --cov=apps.tickets.utils.router \
		--cov-report=term-missing --cov-fail-under=100

.PHONY: typecheck
typecheck: ## mypy on core-api (config lives in the root pyproject.toml)
	cd $(ROOT) && uv run mypy services/core-api

.PHONY: lint
lint: ## ruff check + format check
	$(RUFF) check .
	$(RUFF) format --check .

.PHONY: format
format: ## ruff format, in place
	$(RUFF) format .

.PHONY: check
check: lint typecheck test ## lint + typecheck + test

##@ Run locally (against the Dockerized Postgres/Redis)

.PHONY: runserver
runserver: ## Dev server on :8000
	$(MANAGE) runserver $(ARGS)

.PHONY: worker
worker: ## Celery worker
	uv run celery -A config worker -l info

.PHONY: beat
beat: ## Celery beat (quarantine expiry, weekly drift check)
	uv run celery -A config beat -l info

.PHONY: shell
shell: ## Django shell
	$(MANAGE) shell

##@ Database and schema

.PHONY: makemigrations
makemigrations: ## Generate migrations after a model change
	$(MANAGE) makemigrations $(ARGS)

.PHONY: migrate
migrate: ## Apply migrations
	$(MANAGE) migrate $(ARGS)

.PHONY: seed
seed: ## Load demo users + KB into the database
	$(MANAGE) seed_demo

.PHONY: types
types: ## Regenerate web TS types after a schema change
	uv run python scripts/gen_typescript.py

##@ Help

.PHONY: help
help: ## List targets
	@awk 'BEGIN {FS = ":.*## "} \
		/^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
