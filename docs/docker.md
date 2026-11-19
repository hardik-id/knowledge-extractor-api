# Docker

The API ships as one image, built from `Dockerfile` (multi-stage, after the uv Docker guide): a build stage runs `uv sync --locked --no-dev` and `collectstatic`, the final stage is slim Python 3.14 with the virtual environment and the code, running as the non-root user `app`. WhiteNoise serves the static files.

## Build

    docker build -t knowledge-extractor-api .

## Run with compose

    cp .env.example .env
    docker compose up --build -d api

This starts `db`, waits until it is healthy, applies migrations, starts the server and reports `api` healthy. The API listens on `http://localhost:8000` (`API_PORT` changes the host port); try `/api/v1/health`.

Stop only the API with `docker compose stop api`. The `db` service is shared by every worktree: do not run `docker compose down`.

Compose overrides `DATABASE_URL` so that the container reaches the database as `db:5432`. Everything else comes from `.env`.

## Run the image alone (production settings)

    docker run --rm -p 8000:8000 \
      -e DJANGO_SECRET_KEY=... \
      -e DJANGO_ALLOWED_HOSTS=localhost \
      -e DATABASE_URL=postgres://user:pass@host:5432/name \
      -e AUTH_MODE=entra \
      -e DJANGO_SECURE_SSL_REDIRECT=false \
      knowledge-extractor-api

The image defaults to `config.settings.production`. Migrations are not run by the image's own command; run `python manage.py migrate` as a separate step.

## Variables

| Variable | Needed | Meaning |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | production | Secret key |
| `DJANGO_ALLOWED_HOSTS` | production | Allowed Host headers, comma separated |
| `DATABASE_URL` | yes | PostgreSQL URL |
| `AUTH_MODE` | production | Must be `entra` in production |
| `DJANGO_SECURE_SSL_REDIRECT` | no | Default on; turn off when no TLS proxy is in front |
| `CORS_ALLOWED_ORIGINS`, `ENTRA_*`, `LOG_*`, `API_DOCS_ENABLED` | no | See `.env.example` |

## Worker

`worker` runs `python manage.py db_worker` from the same image (see [jobs.md](jobs.md)). It starts after `api` is healthy and stops on SIGTERM once its current job is done.
