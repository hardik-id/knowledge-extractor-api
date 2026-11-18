---
name: add-model
description: Add or change a Django model in an app of this API, with its migration, factory and admin. Use when data needs a new table or a new field.
---

# Add a model

## Steps

1. In `apps/<app>/models.py` extend `OwnedModel` when the row belongs to one person (gives `owner` and `visible_to(user)`), otherwise `BaseModel` (UUIDv7 `id`, `created_at`, `updated_at`). Both are in `apps/core/models.py`. Models hold data and invariants only. See `docs/permissions.md` if more than the owner may see it.
2. `uv run python manage.py makemigrations <app>`. Never write a migration by hand; review the generated one.
3. A factory in `apps/<app>/tests/factories.py` (`factory.django.DjangoModelFactory`, `owner = factory.SubFactory(UserFactory)` for owned models).
4. Register it in `apps/<app>/admin.py` with `@admin.register`, `list_display` and the `# type: ignore[type-arg]` comment the template shows.
5. A test that uses the factory, then `make check`.

## Done when

`uv run python manage.py makemigrations --check --dry-run` reports no changes and `make check` passes.

## Pitfalls

- Edit a migration that is already on `main` and you break everyone's database: add a new one.
- Foreign keys to another app's model couple the apps; reference by id or go through its services.
- The user model is `identity.User`: use `settings.AUTH_USER_MODEL`, not an import.
