# OneQuickJob. Run everything through make: it supplies INSTANCE (this worktree's
# directory name) so lanes never collide, and falls back to sudo for Docker.
SHELL := /bin/bash
.DEFAULT_GOAL := help

-include .env
INSTANCE ?= $(notdir $(CURDIR))
API_PORT ?= 8000
WEB_PORT ?= 5170
MONGO_DB ?= oqj_main
SITE_HOST ?= dev.onequickjob.co.uk
CADDY_FILES_VOLUME ?= oqj-files-main

SUDO := $(shell docker info >/dev/null 2>&1 || echo sudo)
DOCKER := $(SUDO) docker
COMPOSE := $(SUDO) env INSTANCE=$(INSTANCE) docker compose --env-file .env
SHARED := $(COMPOSE) -f infra/compose.shared.yml
APP := $(COMPOSE) -f infra/compose.app.yml
# Lanes start shared services if they're down but never recreate main's Caddy.
NO_RECREATE := $(if $(filter main,$(INSTANCE)),,--no-recreate)
TEST_ENV := -e MONGO_DB=$(MONGO_DB)_test -e TASKS_ENABLED=false -e SERVE_FILES=false -e DEMO_MODE=true \
            -e SECRET_KEY=test-secret-key-0123456789 -e PAYMENT_GATEWAY=fake -e IDEAL_POSTCODES_KEY=

.PHONY: help env check-env install dev up down infra-up infra-down logs ps test test-api test-web lint lint-api lint-web \
        fmt types types-check seed seed-reset check docs shell-api mongosh

help: ## List the targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  make %-12s %s\n", $$1, $$2}'

env: ## Create .env from .env.example with fresh secrets (never overwrites)
	@if [ -f .env ]; then echo ".env already exists"; else \
	  sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$$(openssl rand -hex 32)|" \
	      -e "s|^BASIC_AUTH_PASSWORD=.*|BASIC_AUTH_PASSWORD=$$(openssl rand -base64 18 | tr -d '/+=')|" \
	      .env.example > .env && chmod 600 .env && echo "Created .env (basic auth: grep BASIC_AUTH .env)"; fi

install: ## Install API and web dependencies on the host (for lint, types and editors)
	cd api && uv sync
	cd web && npm ci --no-audit --no-fund

check-env:
	@test -f .env || { echo "No .env here. Run: make env" >&2; exit 1; }

infra-up: check-env ## Start the shared Mongo and Caddy (idempotent)
	@$(DOCKER) network inspect oqj >/dev/null 2>&1 || $(DOCKER) network create oqj >/dev/null
	@for v in $(CADDY_FILES_VOLUME) oqj-files-$(INSTANCE); do \
	  $(DOCKER) volume inspect $$v >/dev/null 2>&1 || $(DOCKER) volume create $$v >/dev/null; done
	$(SHARED) up -d --wait $(NO_RECREATE)

infra-down: ## Stop the shared Mongo and Caddy (affects every worktree)
	$(SHARED) down

dev: infra-up ## Bring up this worktree's API and web (and shared services)
	$(APP) up -d --build --renew-anon-volumes
	@echo "Waiting for the API..."; for i in $$(seq 1 60); do \
	  curl -fsS http://127.0.0.1:$(API_PORT)/api/health >/dev/null 2>&1 && break; sleep 1; done
	@curl -fsS http://127.0.0.1:$(API_PORT)/api/health && echo
	@echo "API  http://127.0.0.1:$(API_PORT)/api/docs   (this machine only)"
	@echo "Web  http://127.0.0.1:$(WEB_PORT)/           (this machine only; tunnel: ssh -N -L $(WEB_PORT):127.0.0.1:$(WEB_PORT) oqj-dev)"
	@if [ "$(INSTANCE)" = main ]; then echo "Site https://$(SITE_HOST)/  (basic auth: grep BASIC_AUTH .env)"; fi

up: dev

down: ## Stop this worktree's API and web
	$(APP) down

logs: ## Follow this worktree's API and web logs
	$(APP) logs -f --tail=100

ps: ## Show containers
	$(DOCKER) ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

test: test-api test-web ## Run every test

test-api: infra-up ## API tests (pytest, in the api container, against <MONGO_DB>_test)
	$(APP) build api
	$(APP) run --rm --no-deps $(TEST_ENV) api pytest $(ARGS)

test-web: ## Web tests (vitest)
	cd web && npm test

lint: lint-api lint-web types-check ## ruff, eslint, tsc, and generated types up to date

lint-api:
	cd api && uv run ruff check . && uv run ruff format --check .

lint-web:
	cd web && npm run lint && npm run typecheck

fmt: ## Format API code
	cd api && uv run ruff format . && uv run ruff check --fix .

types: ## Regenerate web/src/api/schema.d.ts from the FastAPI OpenAPI schema
	cd api && uv run python -m app.cli.openapi > ../web/src/api/openapi.json
	cd web && npx openapi-typescript src/api/openapi.json -o src/api/schema.d.ts

types-check: ## Fail if the generated API types are stale (run make types)
	@tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	(cd api && uv run python -m app.cli.openapi) > $$tmp/openapi.json && \
	(cd web && npx openapi-typescript $$tmp/openapi.json -o $$tmp/schema.d.ts >/dev/null 2>&1) && \
	diff -q $$tmp/openapi.json web/src/api/openapi.json >/dev/null && diff -q $$tmp/schema.d.ts web/src/api/schema.d.ts >/dev/null \
	  || { echo "Generated API types are stale: run make types" >&2; exit 1; }

seed: infra-up ## Load demo data into this worktree's database (idempotent)
	$(APP) run --rm --no-deps api python -m app.seed

seed-reset: infra-up ## Drop this worktree's database and seed it again
	$(APP) run --rm --no-deps api python -m app.seed --reset

check: ## Fail if anything but Caddy (80, 443) and sshd is exposed publicly
	@DOCKER="$(DOCKER)" infra/check-ports.sh

docs: ## Regenerate docs/spec/notifications.md, api.md and domain.md from the code
	cd api && uv run python -m app.cli.docs notifications > ../docs/spec/notifications.md
	cd api && uv run python -m app.cli.docs api > ../docs/spec/api.md
	cd api && uv run python -m app.cli.docs domain > ../docs/spec/domain.md

shell-api: ## A shell in this worktree's API container
	$(APP) exec api bash

mongosh: ## mongosh against this worktree's database
	$(DOCKER) exec -it oqj-mongo mongosh $(MONGO_DB)
