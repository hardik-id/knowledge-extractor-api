# Architecture

The API serves the [Knowledge Extractor UI](https://github.com/hardik-id/knowledge-extractor). What the UI expects is written down in its repository:

- [auth-api.md](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/auth-api.md): sign-in and the token the API receives.
- [studio-api.md](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/studio-api.md): Knowledge Studio.
- [extraction-api.md](https://github.com/hardik-id/knowledge-extractor/blob/main/docs/extraction-api.md): extraction.

The UI sends an Entra ID access token on every call as `Authorization: Bearer ...`. The API reads the person from the claims and applies its own permissions.

## Today

Django 6.1 project with PostgreSQL (`compose.yaml`), settings per environment in `config/settings/`, and a custom user model in `apps/identity` (`oid` plus `tid`). There are no API endpoints yet.

## Layers

```
config/        wiring: settings, root URLs, ASGI/WSGI
apps/core/     shared components, no domain rules
apps/<domain>/ one app per domain
```

Inside a domain app (the shape `make app name=<name>` gives, see `docs/new-app.md`):

| Part | Job |
| --- | --- |
| `api/` | serializers, views, urls. Thin: parse, call, serialize |
| `services.py` | writes and business rules, take the acting user |
| `selectors.py` | reads, take the acting user |
| `models.py` | data and invariants |

Apps import `apps.core`. They call each other only through services and selectors, never through models.

## Path of a request

Planned: the pieces are issues, not code. Today a request passes Django's default middleware and URL routing only.

1. **Middleware**: request id and structured logging (#13), CORS and security headers (#14), the error contract (#10).
2. **Authentication**: the Entra token is validated (#15), the bearer authentication class finds or creates the user by `oid` and `tid` (#16).
3. **View** (`api/`): permission check (#19), parse the input, call a service or selector, serialize. Routed under `/api/v1` (#12).
4. **Service or selector**: the business rule or the query, scoped to the acting user. An id the person may not see answers 404.
5. **Model**: data and invariants, stored in PostgreSQL.

Errors leave as `{ "code", "message" }` with optional `details`, raised as `ApiError` (#10). `GET /me` (#17) is the endpoint to copy.

## Planned

The roadmap is the tracking issue, [#25](https://github.com/hardik-id/knowledge-extractor-api/issues/25): quality tooling (#5 to #7), Docker image (#9), core components (#10 to #12), platform middleware (#13 to #15), sign-in (#16 to #19), OpenAPI and Swagger (#20, #21), app template and agent skills (#22, #23). Domain apps (documents, runs, extraction, assistant) follow the foundation.
