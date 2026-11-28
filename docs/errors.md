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
| `tenant_not_found` | 404 | Tenant not found. |
| `user_not_found` | 404 | Person not found. |
| `workspace_not_found` | 404 | Workspace not found. |
| `file_not_found` | 404 | File not found. |
| `extraction_not_found` | 404 | This file has no extraction yet. |
| `record_not_found` | 404 | Record not found. |
| `value_not_found` | 404 | Value not found. |
| `revision_conflict` | 409 | The records changed since they were loaded. |
| `unknown_field` | 422 | This record type or field is not in the extraction definition. |
| `invalid_span` | 422 | The span does not match the text. |
| `not_deletable` | 422 | A suggestion cannot be deleted. Reject it instead. |
| `too_many_values` | 422 | This field takes a single value. |
| `upstream_not_ready` | 422 | The file has no text to extract from yet. |
| `no_files` | 422 | A run needs at least one file. |
| `mixed_sources` | 422 | A run cannot mix storage documents with files from other sources. |
| `unsupported_source` | 422 | This source is not supported yet. |
| `definition_conflict` | 409 | Someone saved a newer version of this definition. |
| `invalid_definition` | 422 | The extraction definition is not valid. |
| `definition_version_not_found` | 404 | This version of the definition was not found. |
| `template_not_found` | 404 | Template not found. |
| `custom_chunking_off` | 409 | Custom chunking is turned off on this server. |
| `model_not_configured` | 409 | No language model is configured. |
| `model_unreachable` | 502 | The language model could not be reached. |
| `custom_chunking_failed` | 422 | The assistant could not write splitting code that works on these documents. Try describing it differently. |
| `custom_chunking_timeout` | 504 | Writing the splitting code took too long. Try again. |
| `unknown_template` | 422 | This template does not exist. |
| `assistant_busy` | 409 | The assistant is still answering. |
| `empty_message` | 422 | Write a message first. |
| `run_belongs_to_workspace` | 409 | This run belongs to a workspace. Delete the workspace instead. |
| `execution_in_progress` | 409 | This stage is already running. |
| `unknown_file` | 422 | One of the files is not part of this run. |
| `last_platform_admin` | 409 | The last platform admin cannot be removed. |
| `last_tenant_admin` | 409 | A tenant keeps at least one admin. |
| `last_owner` | 409 | A workspace keeps at least one owner. |
| `already_a_member` | 409 | This person is already a member. |
| `not_a_tenant_member` | 422 | This person is not a member of the workspace's tenant. |
| `tenant_name_taken` | 409 | A tenant with this name already exists. |
| `tenant_not_empty` | 409 | This tenant still has workspaces. Delete or move them first. |
| `default_tenant` | 409 | The default tenant cannot be deleted. |
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
