# Knowledge Extractor API

The Django REST API behind the [Knowledge Extractor and Knowledge Studio UI](https://github.com/hardik-id/knowledge-extractor).

The project is built from its backlog, one PBI per pull request.

- **Backlog:** the [issues](https://github.com/hardik-id/knowledge-extractor-api/issues). The foundation epic is tracked in [#25](https://github.com/hardik-id/knowledge-extractor-api/issues/25).
- **How it gets built:** [docs/delivery.md](docs/delivery.md).
- **What the UI expects from this API:** [sign-in](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/auth-api.md), [Knowledge Studio](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/studio-api.md) and [extraction](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/extraction-api.md), in the UI repository.

## Getting started

Requires [uv](https://docs.astral.sh/uv/). It installs Python 3.14 as pinned in `.python-version`.

```sh
uv sync --locked
uv run python manage.py check
uv run python manage.py runserver
```

The development server answers on http://127.0.0.1:8000/. Do not run `migrate` yet: the custom user model has to be in the first migration.
