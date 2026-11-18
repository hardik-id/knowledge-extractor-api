# Adding an app

A new domain app starts from the template in `scaffolding/app_template/`, so it has the same shape as `apps/identity`.

```sh
make app name=documents
```

This creates `apps/documents/` with `manage.py startapp --template`, then prints the two lines left to add by hand:

```text
# config/settings/base.py, INSTALLED_APPS
"apps.documents",

# config/api_v1.py, urlpatterns
path("", include("apps.documents.api.urls")),
```

After that `make check` passes with no other edit. The name must be a valid Python module name; an existing `apps/<name>/` is never overwritten.

## What you get

```
apps/documents/
  apps.py          AppConfig, name "apps.documents"
  models.py        one placeholder model on OwnedModel (Documents)
  services.py      writes: create_documents(user, name=...)
  selectors.py     reads: list_documents(user), only the caller's rows
  admin.py
  api/             serializers.py, views.py, urls.py (thin)
  migrations/      0001_initial for the placeholder model
  tests/           factories.py, test_api.py, test_services.py
```

The placeholder endpoint is `GET` and `POST /api/v1/documents`. It is left out of `docs/openapi.yaml` (`@extend_schema(exclude=True)`) so a fresh app does not make `make schema-check` fail. When you replace it with the real endpoints, remove `exclude=True` and run `make schema`.

## Make it yours

1. Replace the placeholder model. Delete the generated `migrations/0001_initial.py` (it creates the placeholder table) and run `uv run python manage.py makemigrations documents`.
2. Replace the endpoint, service and selector. Rules: `docs/architecture.md`, `docs/permissions.md`, `docs/errors.md`.
3. Keep the tests: they show how to call the API with a signed-in user and how to use factories.
4. Run `make format` if a long app name made a line too long for the formatter.

The template files end in `-tpl` (`models.py-tpl`): `startapp` renames them, and ruff, mypy and pytest never see them. Change the template by editing those files, then generate an app and run `make check` to prove it still passes.
