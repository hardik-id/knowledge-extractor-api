# Knowledge Extractor API

The Django REST API behind the [Knowledge Extractor and Knowledge Studio UI](https://github.com/hardik-id/knowledge-extractor).

The project is built from its backlog, one PBI per pull request.

- **Backlog:** the [issues](https://github.com/hardik-id/knowledge-extractor-api/issues). The foundation epic is tracked in [#25](https://github.com/hardik-id/knowledge-extractor-api/issues/25).
- **How it gets built:** [docs/delivery.md](docs/delivery.md).
- **What the UI expects from this API:** [sign-in](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/auth-api.md), [Knowledge Studio](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/studio-api.md) and [extraction](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/extraction-api.md), in the UI repository.

## Run it

```sh
cp .env.example .env
make up                  # db, redis, otel-collector, api and worker, healthy
make ui-env              # the .env.local for the UI, with a fresh dev token
```

[docs/manual-testing.md](docs/manual-testing.md) shows how to try each part by hand: the UI, every Studio call with curl, the live socket, telemetry and switching the assistant to a model.

## Getting started

Requires [uv](https://docs.astral.sh/uv/). It installs Python 3.14 as pinned in `.python-version`.

```sh
uv sync --locked
uv run python manage.py check
uv run python manage.py runserver
```

The development server answers on http://127.0.0.1:8000/. Do not run `migrate` yet: the custom user model has to be in the first migration.

### Without Docker for the API

Only the database and Redis need Docker. Run `make db` to start both, then `make migrate`. `make run` starts the API with uvicorn on http://127.0.0.1:8000/ (`make run PORT=8001` for another port), and it serves WebSockets, which `runserver` does not. Jobs, such as assistant replies and extraction, run only while `make worker` runs in a second terminal. `make token` prints a dev token. It mints in the `api` container when that runs, and on the host otherwise. The two are signed by different keys, so a token from one is refused by the other.

## Database

PostgreSQL runs through Docker Compose. The project name is fixed, so every git worktree shares one server.

```sh
docker compose up -d db      # start (waits for the health check with --wait)
docker compose stop db       # stop, data is kept
docker compose down          # remove the container, data is kept in the volume
docker compose down -v       # reset: also deletes the data
```

Credentials are local only: user `ke`, password `ke`, database `ke`. The host port comes from `DB_PORT` (default 5432). `DATABASE_URL` defaults to this server; see `.env.example`.

Check the connection:

```sh
uv run python manage.py shell -c "from django.db import connection; connection.ensure_connection()"
```
