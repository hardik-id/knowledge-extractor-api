# Errors

Every error the API returns has the same JSON body:

```json
{ "code": "validation_error", "message": "The request is not valid.", "details": { "name": ["This field is required."] } }
```

`code` is a stable machine-readable string, `message` is for people, `details` is optional (for `validation_error` it maps each field to its messages). Nothing internal ever appears in the body: a crash answers `server_error` and its traceback goes to the log.

## Codes

The registry is `ERRORS` in `apps/core/errors.py`.

| Code | Status | Default message |
| --- | --- | --- |
| `bad_request` | 400 | The request could not be read. |
| `unauthenticated` | 401 | Authentication is required. |
| `forbidden` | 403 | You do not have permission to do this. |
| `not_found` | 404 | Not found. |
| `method_not_allowed` | 405 | Method not allowed. |
| `document_not_found` | 404 | Document not found. |
| `run_not_found` | 404 | Run not found. |
| `file_not_found` | 404 | File not found. |
| `extraction_not_found` | 404 | This file has no extraction yet. |
| `invalid_span` | 422 | The span does not match the text. |
| `no_files` | 422 | A run needs at least one file. |
| `mixed_sources` | 422 | A run cannot mix storage documents with files from other sources. |
| `unsupported_source` | 422 | This source is not supported yet. |
| `definition_conflict` | 409 | Someone saved a newer version of this definition. |
| `invalid_definition` | 422 | The extraction definition is not valid. |
| `conflict` | 409 | The request conflicts with the current state. |
| `validation_error` | 422 | The request is not valid. |
| `server_error` | 500 | Something went wrong. |
| `not_ready` | 503 | The service is not ready. |

## Raising an error

```python
from apps.core.errors import ApiError

raise ApiError("conflict")  # default message
raise ApiError("conflict", "Name already used.")  # own message
raise ApiError("conflict", details={"name": ["taken"]})
```

An unregistered code raises `ValueError` at once.

## What is mapped

`apps/core/api/exception_handler.py` is the REST framework `EXCEPTION_HANDLER`:

- `ApiError` answers as itself.
- Not authenticated and authentication failed answer 401 `unauthenticated`, keeping `WWW-Authenticate`.
- Permission denied answers 403 `forbidden`; not found answers 404 `not_found`; a wrong method answers 405.
- A serializer validation error answers 422 `validation_error` with the fields in `details`.
- Unreadable JSON answers 400 `bad_request`.
- Anything else answers 500 `server_error`, logged with its traceback.

Outside the REST framework, `config/urls.py` routes every unknown URL under `/api/` to a view that answers 404 `not_found` (also with debug on), and `handler404` and `handler500` answer the same JSON for paths under `/api/` (for example a crash in middleware). Paths outside `/api/` keep Django's pages.

## Adding a code

Add one line to `ERRORS` in `apps/core/errors.py` and one row to the table above. Raise it with `ApiError("<code>")`.
