---
name: add-endpoint
description: Add an API endpoint under /api/v1 (a GET, POST, PATCH or DELETE) with serializer, selector or service, view, url and tests. Use for any new route the UI will call, including a trivial one.
---

# Add an endpoint

Copy `apps/identity/api` (`/me`) or the template's placeholder in `scaffolding/app_template/`. Rules: `docs/api-conventions.md`, `docs/permissions.md`, `docs/errors.md`.

## Steps

1. Reads go in `selectors.py`, writes in `services.py`. Both take the acting user first. A selector on an `OwnedModel` starts with `Model.objects.visible_to(user)`.
2. `api/serializers.py`: input and output shapes, snake_case fields.
3. `api/views.py`: thin. Parse, call the service or selector, serialize. Use `@extend_schema(responses=...)` on function views. Lists answer `{ "items": [...] }` with `DefaultPagination`. Fetch one row with `get_visible_or_404`, never by bare id.
4. `api/urls.py`: path without a trailing slash. The app must already be mounted in `config/api_v1.py`.
5. Tests in `apps/<app>/tests/test_api.py`, through the API with the `api_client` and `user` fixtures (`api_client.force_authenticate(user)`) and factories. Cover the success, a 401 without a token, a 422 for bad input, and a 404 for another person's row.
6. `make schema`, commit the changed `docs/openapi.yaml`, then `make check`.

## Done when

`make check` passes, the endpoint shows in `docs/openapi.yaml`, and a signed-in call returns the expected body.

## Pitfalls

- Endpoints require sign-in by default; do not add `permission_classes` to loosen it unless the issue says so.
- A trailing slash in the path is a 404 here (`APPEND_SLASH = False`).
- Business rules in the view instead of `services.py`.
- A validation failure is 422, not 400. Another person's row is 404, not 403.
- Forgetting `make schema`: `make check` fails on `schema-check`.
