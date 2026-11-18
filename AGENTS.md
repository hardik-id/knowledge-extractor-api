# Knowledge Extractor API

The Django REST API behind the [Knowledge Extractor UI](https://github.com/hardik-id/knowledge-extractor). Python 3.14, Django 6.1, PostgreSQL, managed with uv. The backlog is GitHub issues; the foundation epic is tracked in #25. Where things go and how a request flows: `docs/architecture.md`. How PBIs get built: `docs/delivery.md`.

Anything marked "planned (#nr)" does not exist yet. Do not assume it.

## Commands that exist

```sh
uv sync --locked                          # install
uv run python manage.py check             # system checks
uv run python manage.py runserver         # dev server, http://127.0.0.1:8000/
uv run pytest                           # tests, against PostgreSQL
make test                                 # same, also part of make check
uv run python manage.py makemigrations --check --dry-run
docker compose up -d db                   # PostgreSQL, shared by every worktree
```

Planned: mypy (#6). `make schema` writes `docs/openapi.yaml`; `make check` fails when it is out of date. A tool counts as a check only once its configuration is in the repository.

Never run `docker compose down` or reset `db`: one server serves every worktree. Use your own database and pass it as `DATABASE_URL`.

## Layout

```
config/            wiring only: settings/{base,local,test,production}.py, urls.py, asgi.py, wsgi.py
apps/core/         shared components, no domain rules
apps/identity/     the custom user (oid + tid)
apps/<domain>/     one app per domain, added later
docs/              one file per topic
```

Planned: `apps/<domain>/api/`, `services.py` and `selectors.py` per app, `.claude/skills/` (#23).

## The rules

These are decisions, not suggestions.

1. **Generators first.** `uv add` for dependencies, `manage.py startapp` for apps (`make app name=<name>`, which uses the template), `makemigrations` for migrations, `pre-commit autoupdate` for hook versions, `make schema` for the OpenAPI file. Hand-write only what no generator produces. Never type dependencies into `pyproject.toml`.
2. **Layout.** `config/` is wiring only. `apps/core` holds shared components and no domain rules. One app per domain under `apps/`.
3. **Inside an app.** `api/` (serializers, views, urls) is thin: parse, call, serialize. Writes and business rules live in `services.py`, reads in `selectors.py`, and both take the acting user as an argument. Models hold data and invariants.
4. **Between apps.** Apps import `apps.core`. They do not import each other's models or internals: they call the other app's services and selectors.
5. **API.** Under `/api/v1`, no trailing slash, snake_case JSON, lists as `{ "items": [...] }`. Every error is `{ "code", "message" }` with optional `details`, raised as `ApiError` with a registered code (`docs/errors.md`). A validation failure answers 422.
6. **Sign-in.** Every endpoint requires a signed-in person unless its code says otherwise. The person is `oid` together with `tid`. An id the person may not see answers 404, not 403.
7. **Tests.** With every change, in pytest, against real PostgreSQL, with factories. Test behaviour through the API where there is one.
8. **Workflow.** `make check` passes before a pull request (planned, #5). One PBI per pull request, on a branch `pbi/<nr>-<slug>`. Plain commit messages, no attribution lines. A feature's documentation goes in `docs/<topic>.md`, not in the README.
9. **Settings.** They come from the environment through `config/settings`. A new variable is added to `.env.example` in the same change. No secrets in the repository.

## Git

- Hooks are shared by all worktrees: do not install or change them from a worktree. Run them by hand with `uv run pre-commit run --all-files` once they exist (planned, #5).
- Nothing secret in git: no `.env`, keys or tokens.
