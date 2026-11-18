# OpenAPI schema and Swagger UI

The API describes itself with drf-spectacular.

- Schema: `/api/schema` (YAML by default, JSON with `Accept: application/vnd.oai.openapi+json`).
- Swagger UI: `/api/docs`. Its files come from `drf-spectacular-sidecar`, served by this app, not from a CDN.
- Both are served when `API_DOCS_ENABLED` is on (the default) and answer 404 otherwise.
- Title `Knowledge Extractor API`, version `v1`, server `/api/v1`: paths in the schema are written without that prefix (`/me`).

## What the schema says

- **Sign-in.** `BearerAuthentication` is an HTTP bearer scheme (`bearerAuth`). Every view that uses it shows a lock; open views (`authentication_classes([])`) show none. Use "Authorize" with a dev token (`docs/auth.md`), then "Try it out". With `AUTH_MODE=entra` there is also an `oauth2` scheme (Microsoft sign-in, see `docs/auth.md`).
- **Errors.** One shared `Error` component (`code`, `message`, `details`), and the 401, 403, 404 and 422 responses on every operation. Both live in `apps/core/api/schema.py` (`ApiSchema`); a view does not repeat them.
- **Success bodies.** A function view declares its body with `@extend_schema(responses=Serializer)`. A generic view gets it from `serializer_class`.

## The committed file

`docs/openapi.yaml` is generated, never edited by hand:

```sh
make schema        # writes docs/openapi.yaml
make schema-check  # part of make check: fails when the file is out of date or the generator warns
```

Both use `config.settings.test` with fixed values, so the file does not depend on your `.env`. Change a serializer or a view: run `make schema` and commit the result.
