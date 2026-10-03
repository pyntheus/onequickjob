# OneQuickJob. Run everything through make: it supplies INSTANCE (this worktree's
# directory name) so lanes never collide. Docker runs without sudo (you're in the docker group).
SHELL := /bin/bash
.DEFAULT_GOAL := help

-include .env
INSTANCE ?= $(notdir $(CURDIR))
API_PORT ?= 8000
WEB_PORT ?= 5170
MONGO_DB ?= oqj_main
SITE_HOST ?= dev.onequickjob.co.uk
CADDY_FILES_VOLUME ?= oqj-files-main

DOCKER := docker
COMPOSE := env INSTANCE=$(INSTANCE) docker compose --env-file .env
SHARED := $(COMPOSE) -f infra/compose.shared.yml
APP := $(COMPOSE) -f infra/compose.app.yml
# Lanes start shared services if they're down but never recreate main's Caddy.
NO_RECREATE := $(if $(filter main,$(INSTANCE)),,--no-recreate)
# Tests set their own SECRET_KEY and tax data keys (tests/conftest.py), never this worktree's.
TEST_ENV := -e MONGO_DB=$(MONGO_DB)_test -e TASKS_ENABLED=false -e SERVE_FILES=false -e DEMO_MODE=true \
            -e PAYMENT_GATEWAY=fake -e IDEAL_POSTCODES_KEY=

.PHONY: help env check-env install dev up down infra-up infra-down logs ps test test-api test-web lint lint-api lint-web \
        fmt types types-check seed seed-reset rotate-tax-key check docs shell-api mongosh

help: ## List the targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  make %-12s %s\n", $$1, $$2}'

env: ## Create .env from .env.example with fresh secrets (never overwrites; adds missing tax data keys)
	@if [ -f .env ]; then echo ".env already exists"; else \
	  sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$$(openssl rand -hex 32)|" \
	      -e "s|^BASIC_AUTH_PASSWORD=.*|BASIC_AUTH_PASSWORD=$$(openssl rand -base64 18 | tr -d '/+=')|" \
	      -e "s|^TAX_DATA_KEYS=.*|TAX_DATA_KEYS=k1:$$(openssl rand -base64 32 | tr '+/' '-_')|" \
	      .env.example > .env && chmod 600 .env && echo "Created .env (basic auth: grep BASIC_AUTH .env)"; fi
	@if ! grep -q '^TAX_DATA_KEYS=.' .env; then \
	  sed -i -e '/^TAX_DATA_KEYS=/d' -e '/^TAX_DATA_KEY_CURRENT=/d' .env; \
	  printf 'TAX_DATA_KEYS=k1:%s\nTAX_DATA_KEY_CURRENT=k1\n' "$$(openssl rand -base64 32 | tr '+/' '-_')" >> .env; \
	  echo "Added a tax data key (k1) to .env: copy the TAX_DATA_KEYS line to your password manager"; fi

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

rotate-tax-key: check-env infra-up ## New tax data key: make it current, re-encrypt, then retire the old ones
	cd api && uv run python -m app.cli.tax_keys add --env-file ../.env
	@if [ -n "$$($(DOCKER) ps -q -f name=^oqj-$(INSTANCE)-api$$)" ]; then $(APP) up -d api; fi
	$(APP) run --rm --no-deps api python -m app.cli.tax_keys reencrypt
	cd api && uv run python -m app.cli.tax_keys retire --env-file ../.env
	@if [ -n "$$($(DOCKER) ps -q -f name=^oqj-$(INSTANCE)-api$$)" ]; then $(APP) up -d api; fi

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
