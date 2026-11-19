# Knowledge Extractor API

The Django REST API behind the [Knowledge Extractor UI](https://github.com/hardik-id/knowledge-extractor). Python 3.14, Django 6.1, PostgreSQL, managed with uv. The backlog is GitHub issues; the foundation epic is tracked in #25. Where things go and how a request flows: `docs/architecture.md`. How PBIs get built: `docs/delivery.md`.

## Commands that exist

```sh
uv sync --locked                          # install
uv run python manage.py check             # system checks
uv run python manage.py runserver         # dev server, http://127.0.0.1:8000/
uv run pytest                           # tests, against PostgreSQL
make test                                 # same, also part of make check
make check                                # ruff, mypy, schema-check, pytest: the gate before a pull request
make format                               # ruff format and fix
make schema                               # write docs/openapi.yaml
make app name=<name>                      # new domain app from the template
uv run python manage.py mint_dev_token    # dev bearer token (AUTH_MODE=dev)
uv run python manage.py makemigrations --check --dry-run
docker compose up -d db                   # PostgreSQL, shared by every worktree
```

`make check` fails when `docs/openapi.yaml` is out of date. A tool counts as a check only once its configuration is in the repository.

A fresh worktree starts with `uv sync --locked`, never `make install` (it installs git hooks, which are shared). The shared service is `db` (`redis` and `otel-collector` join it once they exist in `compose.yaml`). Export `DATABASE_URL` for your own database before `make check`, `runserver` or `mint_dev_token`.

Never run `docker compose down` or reset `db`: one server serves every worktree. Use your own database and pass it as `DATABASE_URL`.

## Layout

```
config/            wiring only: settings/{base,local,test,production}.py, urls.py, asgi.py, wsgi.py
apps/core/         shared components, no domain rules
apps/identity/     the custom user (oid + tid)
apps/<domain>/     one app per domain, made with make app: api/, models.py, services.py, selectors.py, tests/
scaffolding/       app_template, used by make app
.claude/skills/    skills for agents (below); .claude/workflows/ are the delivery workflows
docs/              one file per topic (below)
```

## Skills

Load the one that fits the job; each lists its commands, what done looks like and the pitfalls.

| Skill | Use it to |
| --- | --- |
| `add-app` | add a domain app with `make app` and mount it |
| `add-endpoint` | add an endpoint: serializer, selector or service, view, url, tests, `make schema` |
| `add-model` | add a model on `BaseModel` or `OwnedModel`, with migration, factory and admin |
| `add-error-code` | register an error code, raise it, test it |
| `add-setting` | add an environment variable through `config/settings` and `.env.example` |
| `verify` | run `make check`, start the app, call it with a dev token |

## Docs

`architecture.md` where things go and how a request flows; `api-conventions.md` paths, JSON, ids, paging; `errors.md` the error codes; `auth.md` sign-in and dev tokens; `permissions.md` visibility and 404 versus 403; `openapi.md` schema and Swagger UI; `new-app.md` the app template; `logging.md`; `realtime.md` sockets and the ticket; `security.md`; `docker.md`; `jobs.md` background jobs and the worker; `delivery.md` how PBIs are built. `openapi.yaml` is generated.

## The rules

These are decisions, not suggestions.

1. **Generators first.** `uv add` for dependencies, `manage.py startapp` for apps (`make app name=<name>`, which uses the template), `makemigrations` for migrations, `pre-commit autoupdate` for hook versions, `make schema` for the OpenAPI file. Hand-write only what no generator produces. Never type dependencies into `pyproject.toml`.
2. **Layout.** `config/` is wiring only. `apps/core` holds shared components and no domain rules. Infrastructure endpoints with no domain go in `apps/core/api`, next to `health.py`. One app per domain under `apps/`.
3. **Inside an app.** `api/` (serializers, views, urls) is thin: parse, call, serialize. Writes and business rules live in `services.py`, reads in `selectors.py`, and both take the acting user as an argument. Models hold data and invariants.
4. **Between apps.** Apps import `apps.core`. They do not import each other's models or internals: they call the other app's services and selectors.
5. **API.** Under `/api/v1`, no trailing slash, snake_case JSON, lists as `{ "items": [...] }`. Every error is `{ "code", "message" }` with optional `details`, raised as `ApiError` with a registered code (`docs/errors.md`). A validation failure answers 422.
6. **Sign-in.** Every endpoint requires a signed-in person unless its code says otherwise. The person is `oid` together with `tid`. An id the person may not see answers 404, not 403.
7. **Tests.** With every change, in pytest, against real PostgreSQL, with factories. Test behaviour through the API where there is one.
8. **Workflow.** `make check` passes before a pull request. One PBI per pull request, on a branch `pbi/<nr>-<slug>`. Plain commit messages, no attribution lines. A feature's documentation goes in `docs/<topic>.md`, not in the README.
9. **Settings.** They come from the environment through `config/settings`. A new variable is added to `.env.example` in the same change. No secrets in the repository.

## Git

- Hooks are shared by all worktrees: do not install or change them from a worktree. Run them by hand with `uv run pre-commit run --all-files`.
- Nothing secret in git: no `.env`, keys or tokens.
