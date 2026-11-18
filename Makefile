.PHONY: install lint format typecheck run migrate db check

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

check: lint typecheck
