---
name: verify
description: Verify a change in this repository before a pull request by running make check, starting the app and calling it with a dev token. Use after any code change and before opening a pull request.
---

# Verify

## Steps

1. Database: PostgreSQL is one shared `db` service. Never stop or reset it. Create your own database: `docker compose exec -T db createdb -U ke <name>` and pass `DATABASE_URL=postgres://ke:ke@localhost:5432/<name>`.
2. `make check` (ruff, mypy, schema-check, pytest). Fix everything; do not skip a check.
3. `uv run python manage.py makemigrations --check --dry-run` is clean.
4. Start the app on your own port: `DATABASE_URL=... uv run python manage.py migrate` then `... runserver 127.0.0.1:<port>`.
5. Call it with a dev token (`AUTH_MODE=dev`, the local default; `docs/auth.md`):
   ```sh
   TOKEN=$(uv run python manage.py mint_dev_token)
   curl -i -H "Authorization: Bearer $TOKEN" http://127.0.0.1:<port>/api/v1/<path>
   curl -i http://127.0.0.1:<port>/api/v1/<path>   # 401 unauthenticated
   ```
6. Stop the server you started.

## Done when

`make check` passes, the endpoint answers as specified with a token and 401 without, and no server of yours is left running.

## Pitfalls

- `make check` needs PostgreSQL reachable at `DATABASE_URL`.
- `mint_dev_token` refuses to run unless `AUTH_MODE=dev`.
- Run hooks by hand (`uv run pre-commit run --all-files`); never `pre-commit install` from a worktree.
