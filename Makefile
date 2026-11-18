.PHONY: install lint format typecheck run migrate db test check

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

test:
	uv run pytest

# Fixed settings, so the file never depends on this machine's .env.
SCHEMA_ENV = DJANGO_SETTINGS_MODULE=config.settings.test API_DOCS_ENABLED=true

schema:
	$(SCHEMA_ENV) uv run python manage.py spectacular --file docs/openapi.yaml --validate --fail-on-warn

schema-check:
	$(SCHEMA_ENV) uv run python manage.py spectacular --file docs/openapi.check.yaml --validate --fail-on-warn
	@if diff -u docs/openapi.yaml docs/openapi.check.yaml; then rm -f docs/openapi.check.yaml; \
	else rm -f docs/openapi.check.yaml; echo "docs/openapi.yaml is out of date: run make schema"; exit 1; fi

check: lint typecheck schema-check test
