# Is it a stub or the real thing?

`GET /api/v1/status` (signed in, read only) says, for each part of the backend, whether it is a stub or real, and for what is real, whether it works. It reads the settings and stored state, pings the channel layer, and never calls the model.

```json
{"environment": "local", "parts": [
  {"id": "assistant", "mode": "stub", "label": "Scripted", "state": "stub", "checked_at": null, "problem": null}
]}
```

Parts, always in this order: `assistant`, `extraction`, `storage`, `sign_in`, `live_updates`, `worker`. A client must tolerate unknown ids.

| Part | Real when | Label | State |
| --- | --- | --- | --- |
| `assistant` | `ASSISTANT_AGENT=openai` | provider and model name | from the last real call; `unknown` before the first; `failing` with `not_configured` when a setting is missing |
| `extraction` | `EXTRACTOR=llm` | provider and model name | the same |
| `storage` | `DOCUMENT_STORAGE=azure` or `DOCUMENT_CATALOG=http` | Azure Blob storage, Catalog service | `unknown` (no check yet) |
| `sign_in` | `AUTH_MODE=entra` | Microsoft Entra | `ok`: the caller is signed in |
| `live_updates` | the channel layer is Redis | Redis | a ping with a 2 s limit, cached for 10 s per process with one ping in flight: `ok`, or `failing` with `unreachable` or `timeout` |
| `worker` | the tasks backend is the database | Background worker | `failing` with `worker_stalled` when a job has been ready to run for more than 60 s and the worker shows no life: nothing running that started within `EXECUTION_TIMEOUT_SECONDS`, and nothing started or finished in the last 60 s |

`mode` is `stub` or `real`. `state` is `stub` (nothing to check), `ok`, `failing` or `unknown` (real, not checked yet). `checked_at` is when the state was learned. `problem` is a short code: `auth_failed`, `not_found`, `rate_limited`, `timeout`, `unreachable`, `bad_request`, `error`, `not_configured`, `worker_stalled`. The body never holds an address, a key, an error message or a response body.

## Testing now

`POST /api/v1/status/test` (needs `status.test`: platform admins only; anybody else is 403 `forbidden`) checks every real part now and answers the same body as `GET /api/v1/status`. It makes one model call of a few tokens (16 output tokens, the least the OpenAI Responses API takes; 20 s limit) for the provider and model in use (the assistant and the extractor share one call) and writes the outcome for each real model part, past the write throttle. It pings the channel layer afresh and refreshes the 10 s cache. Storage stays `unknown` and untested: its backends are not built; the read comes when they are. The header is exposed to the browser through CORS (`CORS_EXPOSE_HEADERS`). A failure is a `failing` state with a short code; the endpoint still answers 200. The call runs in a thread of its own and the whole test waits at most 3 s beyond the 20 s limit, so a hung sign-in cannot hold the request longer; it then reports `timeout` and the thread is abandoned. The model's answer is neither returned nor logged, and an unusable answer counts as reached.

One real test per 60 s for the whole deployment: the claim is one conditional UPDATE on the row of `core_status_test_claim`, using the database's clock, so it holds across processes and concurrent requests. The header `X-Status-Test` says what happened: `run`, `cached` (the stored result is returned, no call is made) or `skipped` (nothing testable is real: stubs, a model with a missing setting, an in-memory channel layer; nothing is claimed or called).

## Recording

Every real model call of the assistant and of the extractor records its outcome in the table `core_model_call`, one row per part (`apps/core/status.py`, `record_call`, `arecord_call` from async code). The code comes from `describe_failure`: the HTTP status and the error's class, never the message. A repeated outcome is written at most once per 30 s per process; a changed outcome is written at once. A failure to record is logged and never fails or delays the call. Only what says something about the model is recorded: an answer that could not be used counts as success (the model was reached), and a run's own time budget running out records nothing. A single model call that times out records `timeout`.

## The start line

The API (`config/asgi.py`) and the worker (`manage.py db_worker`) each log one line when they start, for example `backend status assistant=openai extractor=llm provider=azure model=gpt-5 storage=samples catalog=samples auth=dev`. Management commands such as `migrate` do not log it.

A real mode with a missing setting warns at start (the system checks, `assistant.W001` and the extraction check) and shows as `failing` with `not_configured` in the status.
