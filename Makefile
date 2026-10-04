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
# HOST_UID/HOST_GID: the web container runs as you, so nothing in the worktree ends up root's.
COMPOSE := env INSTANCE=$(INSTANCE) HOST_UID=$(shell id -u) HOST_GID=$(shell id -g) docker compose --env-file .env
SHARED := $(COMPOSE) -f infra/compose.shared.yml
APP := $(COMPOSE) -f infra/compose.app.yml
PROD := $(COMPOSE) -f infra/compose.prod.yml
PROD_API_PORT ?= 8090
BACKUP_DIR ?= /srv/oqj/backups
# Lanes start shared services if they're down but never recreate main's Caddy.
NO_RECREATE := $(if $(filter main,$(INSTANCE)),,--no-recreate)
# Tests set their own SECRET_KEY and tax data keys (tests/conftest.py), never this worktree's.
TEST_ENV := -e MONGO_DB=$(MONGO_DB)_test -e TASKS_ENABLED=false -e SERVE_FILES=false -e DEMO_MODE=true \
            -e PAYMENT_GATEWAY=fake -e IDEAL_POSTCODES_KEY=

.PHONY: help env check-env install dev up down infra-up infra-down logs ps test test-api test-web lint lint-api lint-web \
        fmt types types-check seed seed-reset rotate-tax-key rotate-tax-key-locked check docs shell-api mongosh \
        prod-web prod-up prod-down prod-logs status backup-now restore-test backup-timer e2e

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
	@mkdir -p var/www  # Caddy serves the built app from here: yours, before Docker can make it as root
	@$(DOCKER) network inspect oqj >/dev/null 2>&1 || $(DOCKER) network create oqj >/dev/null
	@for v in $(CADDY_FILES_VOLUME) oqj-files-$(INSTANCE); do \
	  $(DOCKER) volume inspect $$v >/dev/null 2>&1 || $(DOCKER) volume create $$v >/dev/null; done
	$(SHARED) up -d --wait $(NO_RECREATE)

infra-down: ## Stop the shared Mongo and Caddy (affects every worktree)
	$(SHARED) down

dev: infra-up ## Bring up this worktree's API and web (and shared services)
	@mkdir -p web/node_modules  # yours, before Docker can create the mount point as root
	@# The dev API shares oqj_main with the production-style API: only one of them runs the
	@# periodic tasks. (Start prod while dev is up? Run make dev again.)
	@tasks=true; if $(DOCKER) ps -q -f name=^oqj-prod-api$$ | grep -q .; then tasks=false; \
	  echo "The production-style API is running and does the periodic tasks, so this dev API won't."; fi; \
	  DEV_TASKS_ENABLED=$$tasks $(APP) up -d --build --renew-anon-volumes
	@echo "Waiting for the API..."; for i in $$(seq 1 60); do \
	  curl -fsS http://127.0.0.1:$(API_PORT)/api/health >/dev/null 2>&1 && break; sleep 1; done
	@curl -fsS http://127.0.0.1:$(API_PORT)/api/health && echo
	@echo "API  http://127.0.0.1:$(API_PORT)/api/docs   (this machine only)"
	@echo "Web  http://127.0.0.1:$(WEB_PORT)/           (this machine only; tunnel: ssh -N -L $(WEB_PORT):127.0.0.1:$(WEB_PORT) oqj-dev)"
	@if [ "$(INSTANCE)" = main ]; then echo "Site https://$(SITE_HOST)/ serves the production-style build: make prod-up"; fi

up: dev

# ---------------------------------------------------------------- production-style run
prod-web: ## Build the web app into var/www, where Caddy serves it
	@test -d web/node_modules/.bin || (cd web && npm ci --no-audit --no-fund)
	cd web && npm run build -- --outDir ../var/build --emptyOutDir
	@# In place (Caddy's bind mount follows the directory, not its name); assets before index.html.
	rsync -a --delete-after var/build/ var/www/

prod-up: infra-up prod-web ## Production-style: the built web app via Caddy, the API without reload (restarts on its own, also after a reboot)
	$(PROD) up -d --build --wait --remove-orphans
	@$(MAKE) --no-print-directory status

prod-down: ## Stop the production-style API (Caddy keeps serving the built app; /api answers 502 until prod-up)
	$(PROD) down

prod-logs: ## Follow the production-style API's logs
	$(PROD) logs -f --tail=100

status: ## Container health, then the API's health directly and through Caddy (basic auth from .env)
	@SITE_HOST=$(SITE_HOST) PROD_API_PORT=$(PROD_API_PORT) scripts/status.sh

e2e: ## Playwright journeys and accessibility checks at 375px and desktop, against the production-style stack (re-seeds)
	@scripts/e2e.sh $(ARGS)

# ---------------------------------------------------------------- backups
backup-now: ## Dump $(MONGO_DB) now into /srv/oqj/backups (gzip; 14 days kept)
	@MONGO_DB=$(MONGO_DB) BACKUP_DIR=$(BACKUP_DIR) scripts/backup.sh

restore-test: ## Restore the latest backup into a scratch database, compare counts with $(MONGO_DB), drop it
	@MONGO_DB=$(MONGO_DB) BACKUP_DIR=$(BACKUP_DIR) scripts/restore-test.sh

backup-timer: ## Install the nightly backup (03:00 Europe/London) as a systemd timer (uses sudo)
	@scripts/install-backup-timer.sh

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

seed: infra-up ## Reset the demo data in this worktree's database (idempotent; keeps admins' pricing versions)
	$(APP) run --rm --no-deps api python -m app.seed

seed-reset: infra-up ## Drop this worktree's database and seed it again
	$(APP) run --rm --no-deps api python -m app.seed --reset

rotate-tax-key: check-env infra-up ## New tax data key: make it current, re-encrypt, then retire the old ones
	@mkdir -p var; flock -n -E 75 var/rotate-tax-key.lock $(MAKE) --no-print-directory rotate-tax-key-locked; rc=$$?; \
	  [ $$rc -ne 75 ] || echo "Another make rotate-tax-key is running in this worktree: wait for it." >&2; exit $$rc

# One rotation at a time (the lock above). reencrypt and retire act only on the key add made.
rotate-tax-key-locked:
	@set -e; kid=$$(cd api && uv run --quiet python -m app.cli.tax_keys add --env-file ../.env); \
	  api=$$($(DOCKER) ps -q -f name=^oqj-$(INSTANCE)-api$$); \
	  if [ -n "$$api" ]; then $(APP) up -d api; fi; \
	  $(APP) run --rm --no-deps api python -m app.cli.tax_keys reencrypt --expect-current $$kid; \
	  (cd api && uv run --quiet python -m app.cli.tax_keys retire --env-file ../.env --keep $$kid); \
	  if [ -n "$$api" ]; then $(APP) up -d api; fi

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
