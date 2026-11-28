---
name: add-endpoint
description: Add an API endpoint under /api/v1 (a GET, POST, PATCH or DELETE) with serializer, selector or service, view, url and tests. Use for any new route the UI will call, including a trivial one.
---

# Add an endpoint

Copy `apps/identity/api` (`/me`) for an endpoint with a model, selector and serializer, or the template's placeholder in `scaffolding/app_template/`. For an endpoint without data, copy `apps/core/api/health.py`: a function view with `@extend_schema(responses=...)` and a plain `serializers.Serializer`, which needs `# type: ignore[type-arg]` for mypy.

Where it goes: a domain endpoint in that domain's app. An infrastructure endpoint with no domain (like `health`) goes in `apps/core/api`, next to `health.py`, with its line in `apps/core/api/urls.py`. Rules: `docs/api-conventions.md`, `docs/permissions.md`, `docs/errors.md`.

## Steps

1. Reads go in `selectors.py`, writes in `services.py`. Both take the acting user first. A selector on an `OwnedModel` starts with `Model.objects.visible_to(user)`.
2. `api/serializers.py`: input and output shapes, snake_case fields.
3. `api/views.py`: thin. Parse, call the service or selector, serialize. Declare what each method needs with `@requires(...)` (`apps/iam/routes.py`) above `@extend_schema` and `@api_view`: a `Permission` of `apps/iam/roles.py`, `SIGNED_IN` or `OPEN`, one keyword per method (`@requires(GET=Permission.WORKSPACE_VIEW, PUT=Permission.WORKSPACE_EDIT)`). A route without it fails the route sweep (`apps/iam/tests/test_route_sweep.py`). Use `@extend_schema(responses=...)` on function views. Lists answer `{ "items": [...] }` with `DefaultPagination`. Fetch a run or a workspace with the permission the call needs (`runs.get_run(user, run_id, Permission.WORKSPACE_EDIT)`), another row with `get_visible_or_404`, never by bare id.
4. `api/urls.py`: path without a trailing slash. An existing app is already mounted in `config/api_v1.py`; only its `urls.py` needs a line. Mount it there only for a new app (`add-app`).
5. Tests in `apps/<app>/tests/test_api.py`, through the API with the `api_client` and `user` fixtures, defined in the root `conftest.py`, and factories. Prefer `api_client.force_authenticate(user)`: it needs no token set-up. `test_me.py` signs in with real tokens (`make_token`) because it tests the sign-in path itself, and `test_health.py` uses a plain `APIClient()` because those routes are open; use real tokens only when the test is about authentication. Cover the success, a 401 without a token, a 422 for bad input, a 404 for a row the person may not see, and a 403 for a role without the permission. If the route's body must pass validation to reach the permission check, add one to `BODIES` in the sweep; if it needs a new id, add it to the sweep's fixture. For the 401, call the endpoint with a client that did not `force_authenticate`: the `api_client` fixture is fresh for each test, so a test that simply does not call `force_authenticate` gets the 401 (or use `APIClient()` from `rest_framework.test`). An endpoint without data needs only the success and the 401 (an open endpoint like `health` has no 401); the 422 and 404 cases need input or a row.
6. `make schema`, commit the changed `docs/openapi.yaml`, then `make check`. Nothing else in `docs/` is needed for a new endpoint; touch `docs/` only when it adds a convention, an error code or a setting.

## Done when

`make check` passes (the route sweep included), the endpoint shows in `docs/openapi.yaml` and in the route table of `docs/iam.md`, and a signed-in call returns the expected body.

## Pitfalls

- Endpoints require sign-in by default; do not add `permission_classes`: say `OPEN` in `@requires` only when the issue says so.
- The declaration and the service must agree: the service fetches with the same permission the view declares, or the sweep fails.
- A trailing slash in the path is a 404 here (`APPEND_SLASH = False`).
- Business rules in the view instead of `services.py`.
- A validation failure is 422, not 400. Another person's row is 404, not 403.
- Forgetting `make schema`: `make check` fails on `schema-check`.
