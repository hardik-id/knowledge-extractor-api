---
name: verify
description: Verify a change in this repository before a pull request by running make check, starting the app and calling it with a dev token. Use after any code change and before opening a pull request.
---

# Verify

## Steps

0. In a fresh worktree run `uv sync --locked` first. Never `make install` there: it installs git hooks, which are shared by all worktrees.
1. Database: PostgreSQL is one shared `db` service (the same one for every worktree). Never stop or reset it. Create your own database with the compose file of the main checkout, so it works from any worktree: `docker compose -f <main checkout>/compose.yaml exec -T db createdb -U ke <name>`. Then export it for this shell: `export DATABASE_URL=postgres://ke:ke@localhost:5432/<name>`. `make check`, `migrate`, `runserver` and `mint_dev_token` all read it.
2. `make check` (ruff, mypy, schema-check, pytest). Fix everything; do not skip a check.
3. `uv run python manage.py makemigrations --check --dry-run` is clean.
4. Start the app on your own port, saving its process id: `uv run python manage.py migrate`, then `uv run python manage.py runserver 127.0.0.1:<port> --noreload & echo $! > /tmp/<name>.pid`.
5. Call it with a dev token (`AUTH_MODE=dev`, the local default; `docs/auth.md`):
   ```sh
   TOKEN=$(uv run python manage.py mint_dev_token)
   curl -i -H "Authorization: Bearer $TOKEN" http://127.0.0.1:<port>/api/v1/<path>
   curl -i http://127.0.0.1:<port>/api/v1/<path>   # 401 unauthenticated
   ```
6. Stop the server you started by its saved id: `kill $(cat /tmp/<name>.pid)`. Do not use `pkill -f` on the runserver command line: it also matches and kills the shell that runs it.

## Done when

`make check` passes, the endpoint answers as specified with a token and 401 without, and no server of yours is left running.

## Pitfalls

- `make check` needs PostgreSQL reachable at `DATABASE_URL`; export it before `make check`, `runserver` or `mint_dev_token`, or they use the default database.
- An open endpoint (such as `/health`) has no 401 case: skip the unauthenticated call for it.
- `mint_dev_token` refuses to run unless `AUTH_MODE=dev`.
- Run hooks by hand (`uv run pre-commit run --all-files`); never `pre-commit install` from a worktree.
