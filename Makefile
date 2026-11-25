.PHONY: help install lint format typecheck run migrate db worker test check app up logs token ui-env e2e e2e-report chart-check install-ant schema schema-check

.DEFAULT_GOAL := help

# The list below is built from the `## text` after each target: add one to every new target.
help: ## List the available commands
	@echo "Usage: make <command>"
	@echo
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies and the pre-commit hooks
	uv sync
	uv run pre-commit install

lint: ## Check lint and formatting (ruff)
	uv run ruff check .
	uv run ruff format --check .

format: ## Format and auto-fix (ruff)
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Type-check (mypy)
	uv run mypy .

# The Anthropic CLI, for LLM_PROVIDER=anthropic in local testing (docs/assistant.md). Needs sudo.
ANT_VERSION = 2.12.1

install-ant: ## Install the Anthropic CLI for LLM_PROVIDER=anthropic (needs sudo)
	@set -e; \
	os=$$(uname -s | tr '[:upper:]' '[:lower:]'); \
	case $$(uname -m) in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; \
	*) echo "install-ant: unsupported architecture $$(uname -m)"; exit 1 ;; esac; \
	curl -fsSL "https://github.com/anthropics/anthropic-cli/releases/download/v$(ANT_VERSION)/ant_$(ANT_VERSION)_$${os}_$${arch}.tar.gz" | sudo tar -xz -C /usr/local/bin ant; \
	echo "Installed ant $(ANT_VERSION). Next: ant auth login, then set LLM_PROVIDER=anthropic and LLM_MODEL=claude-haiku-5-5 in .env"

# The API on the host, with WebSockets (runserver does not serve them). Usage: make run [PORT=8000]
PORT ?= 8000

run: ## Run the API on the host, with WebSockets [PORT=8000]
	uv run uvicorn config.asgi:application --reload --no-access-log --host 127.0.0.1 --port $(PORT)

migrate: ## Apply the database migrations
	uv run python manage.py migrate

# The database and Redis (live updates need Redis).
db: ## Start the database and Redis in Docker
	docker compose up -d --wait db redis

# The background job worker (docs/jobs.md). Stop it with Ctrl+C.
worker: ## Run the background job worker
	uv run python manage.py db_worker

test: ## Run the tests (pytest)
	uv run pytest

# The whole stack in Docker (docs/manual-testing.md): db, redis, otel-collector, api and worker.
# With LLM_PROVIDER=anthropic and no ANTHROPIC_API_KEY, the containers get the token of the
# host's `ant auth login` (they cannot see the login itself). It lasts about eight hours:
# make up again renews it. The token is never printed.
up: ## Start the whole stack in Docker
	@if grep -qx 'LLM_PROVIDER=anthropic' .env 2>/dev/null \
		&& ! grep -qE '^ANTHROPIC_API_KEY=.' .env \
		&& [ -z "$$ANTHROPIC_API_KEY" ] && command -v ant >/dev/null; then \
		if ANTHROPIC_API_KEY=$$(ant auth print-credentials --access-token 2>/dev/null) \
			&& [ -n "$$ANTHROPIC_API_KEY" ]; then \
			export ANTHROPIC_API_KEY; \
			echo "make up: the containers use the token of ant auth login (about eight hours)"; \
		else \
			unset ANTHROPIC_API_KEY; \
			echo "make up: no ant sign-in found; run ant auth login, then make up again"; \
		fi; \
	fi; \
	docker compose up -d --build --wait

logs: ## Follow the api, worker and otel-collector logs
	docker compose logs -f --tail=100 api worker otel-collector

# A dev token, valid for eight hours. Minted in the api container when it runs, else on the host
# (the key of `make run`). Only the token goes to stdout; the two keys differ.
token: ## Mint a dev token, valid for eight hours
	@if command -v docker >/dev/null 2>&1 \
		&& docker compose ps --status running --services 2>/dev/null | grep -qx api; then \
		docker compose exec -T api python manage.py mint_dev_token --ttl 28800; \
	else \
		echo "make token: no api container running, minting on the host" >&2; \
		uv run python manage.py mint_dev_token --ttl 28800; \
	fi

# The .env.local for the UI, with a fresh token. Usage: make ui-env > ../knowledge-extractor/.env.local
ui-env: ## Print the UI's .env.local with a fresh token
	@echo NEXT_PUBLIC_BACKEND_MODE=http
	@echo NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
	@echo NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000
	@echo NEXT_PUBLIC_APPS=studio
	@echo NEXT_PUBLIC_DEV_ACCESS_TOKEN=$$($(MAKE) -s token)

# The UI's end-to-end tests against this stack (docs/manual-testing.md). Usage: make e2e [ARGS="e2e/smoke.spec.ts"]
UI_DIR ?= ../knowledge-extractor

e2e: ## Run the UI's end-to-end tests against this stack [ARGS=<spec>]
	@test -d "$(UI_DIR)" || { echo "UI_DIR $(UI_DIR) not found: set UI_DIR to the knowledge-extractor checkout"; exit 1; }
	@test -d "$(UI_DIR)/node_modules" || { echo "$(UI_DIR)/node_modules is missing: run npm ci in $(UI_DIR)"; exit 1; }
	$(MAKE) up
	cd "$(UI_DIR)" && npm run test:e2e -- $(ARGS)

# The Helm chart (docs/deploy.md): lint, render with both values files, validate against the Kubernetes schemas. Not part of make check.
chart-check: ## Lint, render and validate the Helm chart
	@deploy/helm/chart-check.sh

# Where the Playwright report of the last e2e run is, and how to open it.
e2e-report: ## Show where the report of the last e2e run is
	@test -d "$(UI_DIR)/playwright-report" || { echo "No report in $(UI_DIR)/playwright-report: run make e2e first"; exit 1; }
	@echo "Report: $(UI_DIR)/playwright-report/index.html"
	@echo "Open it with: cd $(UI_DIR) && npx playwright show-report"

# Fixed settings, so the file never depends on this machine's .env.
SCHEMA_ENV = DJANGO_SETTINGS_MODULE=config.settings.test API_DOCS_ENABLED=true

schema: ## Regenerate docs/openapi.yaml
	$(SCHEMA_ENV) uv run python manage.py spectacular --file docs/openapi.yaml --validate --fail-on-warn

schema-check: ## Fail if docs/openapi.yaml is out of date
	$(SCHEMA_ENV) uv run python manage.py spectacular --file docs/openapi.check.yaml --validate --fail-on-warn
	@if diff -u docs/openapi.yaml docs/openapi.check.yaml; then rm -f docs/openapi.check.yaml; \
	else rm -f docs/openapi.check.yaml; echo "docs/openapi.yaml is out of date: run make schema"; exit 1; fi

check: lint typecheck schema-check test ## Run lint, typecheck, schema-check and test

# Usage: make app name=<name>. Creates apps/<name>/ from scaffolding/app_template.
app: ## Create apps/<name>/ from the template [name=<name>]
	@test -n "$(name)" || { echo "usage: make app name=<name>"; exit 1; }
	@test ! -e apps/$(name) || { echo "apps/$(name) already exists"; exit 1; }
	mkdir apps/$(name)
	uv run python manage.py startapp --template scaffolding/app_template $(name) apps/$(name)
	@echo
	@echo "Two lines left to add by hand:"
	@echo '  config/settings/base.py, INSTALLED_APPS:  "apps.$(name)",'
	@echo '  config/api_v1.py, urlpatterns:            path("", include("apps.$(name).api.urls")),'
