.PHONY: install lint format typecheck run migrate db worker test check app up logs token ui-env e2e e2e-report

install:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy .

run:
	uv run python manage.py runserver

migrate:
	uv run python manage.py migrate

db:
	docker compose up -d --wait db

# The background job worker (docs/jobs.md). Stop it with Ctrl+C.
worker:
	uv run python manage.py db_worker

test:
	uv run pytest

# The whole stack in Docker (docs/manual-testing.md): db, redis, otel-collector, api and worker.
up:
	docker compose up -d --build --wait

logs:
	docker compose logs -f --tail=100 api worker otel-collector

# A dev token from the running api, valid for eight hours.
token:
	@docker compose exec -T api python manage.py mint_dev_token --ttl 28800

# The .env.local for the UI, with a fresh token. Usage: make ui-env > ../knowledge-extractor/.env.local
ui-env:
	@echo NEXT_PUBLIC_BACKEND_MODE=http
	@echo NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
	@echo NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000
	@echo NEXT_PUBLIC_APPS=studio
	@echo NEXT_PUBLIC_DEV_ACCESS_TOKEN=$$($(MAKE) -s token)

# The UI's end-to-end tests against this stack (docs/manual-testing.md). Usage: make e2e [ARGS="e2e/smoke.spec.ts"]
UI_DIR ?= ../knowledge-extractor

e2e:
	@test -d "$(UI_DIR)" || { echo "UI_DIR $(UI_DIR) not found: set UI_DIR to the knowledge-extractor checkout"; exit 1; }
	@test -d "$(UI_DIR)/node_modules" || { echo "$(UI_DIR)/node_modules is missing: run npm ci in $(UI_DIR)"; exit 1; }
	$(MAKE) up
	cd "$(UI_DIR)" && npm run test:e2e -- $(ARGS)

# Where the Playwright report of the last e2e run is, and how to open it.
e2e-report:
	@test -d "$(UI_DIR)/playwright-report" || { echo "No report in $(UI_DIR)/playwright-report: run make e2e first"; exit 1; }
	@echo "Report: $(UI_DIR)/playwright-report/index.html"
	@echo "Open it with: cd $(UI_DIR) && npx playwright show-report"

# Fixed settings, so the file never depends on this machine's .env.
SCHEMA_ENV = DJANGO_SETTINGS_MODULE=config.settings.test API_DOCS_ENABLED=true

schema:
	$(SCHEMA_ENV) uv run python manage.py spectacular --file docs/openapi.yaml --validate --fail-on-warn

schema-check:
	$(SCHEMA_ENV) uv run python manage.py spectacular --file docs/openapi.check.yaml --validate --fail-on-warn
	@if diff -u docs/openapi.yaml docs/openapi.check.yaml; then rm -f docs/openapi.check.yaml; \
	else rm -f docs/openapi.check.yaml; echo "docs/openapi.yaml is out of date: run make schema"; exit 1; fi

check: lint typecheck schema-check test

# Usage: make app name=<name>. Creates apps/<name>/ from scaffolding/app_template.
app:
	@test -n "$(name)" || { echo "usage: make app name=<name>"; exit 1; }
	@test ! -e apps/$(name) || { echo "apps/$(name) already exists"; exit 1; }
	mkdir apps/$(name)
	uv run python manage.py startapp --template scaffolding/app_template $(name) apps/$(name)
	@echo
	@echo "Two lines left to add by hand:"
	@echo '  config/settings/base.py, INSTALLED_APPS:  "apps.$(name)",'
	@echo '  config/api_v1.py, urlpatterns:            path("", include("apps.$(name).api.urls")),'
