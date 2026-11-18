---
name: add-app
description: Add a new domain app (documents, runs, extraction, ...) to this API. Use whenever a feature needs its own app under apps/, before writing any model or endpoint for it.
---

# Add an app

One app per domain. Never create the folder by hand: the template gives it the shape of `apps/identity`. Details: `docs/new-app.md`.

## Steps

1. `make app name=<name>` (a valid Python module name, lowercase, plural noun like `documents`).
2. Add the two lines it prints, by hand:
   - `config/settings/base.py`, `INSTALLED_APPS`: `"apps.<name>",`
   - `config/api_v1.py`, `urlpatterns`: `path("", include("apps.<name>.api.urls")),`
3. Replace the placeholder model: delete `apps/<name>/migrations/0001_initial.py`, write the real model (see `add-model`), then `uv run python manage.py makemigrations <name>`. Regenerating `0001_initial.py` is fine only because the app is new and unmerged: no database has applied it. This is not the migration editing that `add-model` warns about; once a migration is merged, never edit it.
4. Replace the placeholder endpoint, service, selector and tests (see `add-endpoint`). Drop `@extend_schema(exclude=True)` and run `make schema`.
5. `make check`.

## Done when

`make check` passes, the app is in `INSTALLED_APPS` and mounted in `config/api_v1.py`, and no placeholder name remains.

## Pitfalls

- The placeholder endpoint is excluded from the schema so a fresh app passes. Once you replace it, the exclusion must go, or the endpoint is undocumented.
- Keeping the generated `0001_initial.py` after changing the model leaves a migration for the placeholder table.
- Apps do not import each other's models: call the other app's `services` and `selectors`.
